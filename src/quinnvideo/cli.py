"""Command-line entry point.

Every pipeline stage is its own subcommand. That is not tidiness for its own
sake: narration and avatar rendering cost credits and minutes, so a failure
in compositing must never re-buy them, and the grading loop needs to rebuild
the visual half on its own.

Claude drives these commands in sequence and supplies the judgement the
scripts cannot -- writing the script, and deciding which stock clips actually
show what the narration describes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import cache, doctor
from .config import ConfigError


def _log(message: str) -> None:
    print(message, flush=True)


def _resolve_run(value: str | None):
    from .runs import Run

    if value:
        return Run.open(Path(value))
    return Run.latest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quinn-video",
        description="Turn a topic into a finished short-form educational video.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def with_run(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--run", help="run directory (default: most recent)")
        p.add_argument("--force", action="store_true", help="ignore cached output")
        return p

    doctor = sub.add_parser("doctor", help="check the toolchain and credentials")
    group = doctor.add_mutually_exclusive_group()
    group.add_argument("--list-avatars", action="store_true", help="print pickable avatar ids")
    group.add_argument("--list-voices", action="store_true", help="print pickable voice ids")
    doctor.add_argument("--search", help="filter the listing by name")
    doctor.add_argument("--limit", type=int, default=40, help="how many to show")

    sub.add_parser("fonts", help="download the bundled caption typefaces")

    aud = sub.add_parser("audition", help="rank voices by how lively they read, at a matched rate")
    aud.add_argument("--limit", type=int, default=24, help="how many voices to try")

    init = sub.add_parser("init", help="create a run directory for a topic")
    init.add_argument("topic")
    init.add_argument(
        "--draft",
        action="store_true",
        help="write a storyboard without the credentials to render it",
    )

    check = sub.add_parser("check", help="validate a storyboard and report its pacing")
    check.add_argument("--run")

    plan = sub.add_parser(
        "plan", help="print the script and what it will cost, for approval before spending"
    )
    plan.add_argument("--run")

    sources = sub.add_parser("sources", help="list numeric claims that still need a primary source")
    sources.add_argument("--run")

    with_run(sub.add_parser("narrate", help="synthesise the voiceover (costs credits)"))
    avatar = with_run(sub.add_parser("avatar", help="render the presenter (costs credits)"))
    avatar.add_argument(
        "--submit",
        action="store_true",
        help="queue the render and return, so b-roll can proceed while it runs",
    )
    avatar.add_argument("--collect", action="store_true", help="wait for a queued render")
    with_run(sub.add_parser("overlay", help="draw the caption layer"))

    gather = with_run(sub.add_parser("broll", help="search stock footage for every beat"))
    gather.add_argument("--per-query", type=int, default=8)

    sheets = with_run(
        sub.add_parser(
            "sheet", help="render labelled contact sheets of the candidates, to judge by eye"
        )
    )
    sheets.add_argument("--beat", type=int, help="only this beat")

    fetch = with_run(sub.add_parser("fetch", help="download the chosen footage"))
    fetch.add_argument("--picks", help="picks JSON (default: <run>/picks.json)")

    build = with_run(sub.add_parser("build", help="composite the finished video"))
    build.add_argument(
        "--music",
        help="music bed: a path, or 'auto' to generate one from the topic",
    )
    build.add_argument("--mood", default="", help="extra direction for an auto bed")

    probe = sub.add_parser(
        "probe", help="test whether an avatar supports transparent output (~$0.22)"
    )
    probe.add_argument("--avatar", help="avatar id (default: QUINN_AVATAR_ID)")
    probe.add_argument("--voice", help="voice id (default: QUINN_VOICE_ID)")
    probe.add_argument("--engine", default="avatar_iii", help="cheapest engine by default")
    probe.add_argument("--keep", help="where to save the probe render")

    cands = with_run(
        sub.add_parser(
            "candidates", help="draw several options per generated shot, to choose between"
        )
    )
    cands.add_argument("--count", type=int, default=3)
    cands.add_argument("--beat", type=int, help="only this beat")
    cands.add_argument("--model", help="override the image model")

    with_run(sub.add_parser("verify", help="pair every shot with the words spoken over it"))
    with_run(sub.add_parser("grade", help="score the finished video and write a scorecard"))
    with_run(sub.add_parser("status", help="show what a run has produced so far"))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        # Every stage states what it needs and stops here if it is missing,
        # rather than failing partway through with the expensive calls already
        # made. Set QUINN_SKIP_PREFLIGHT to bypass.
        doctor.preflight(args.command, bypass=getattr(args, "draft", False))
        return _dispatch(args)
    except doctor.NotReadyError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"\n\033[31mconfiguration error\033[0m: {exc}\n", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"\n\033[31mmissing\033[0m: {exc}\n", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "doctor":
        if args.list_avatars:
            return doctor.list_avatars(args.search, limit=args.limit)
        if args.list_voices:
            return doctor.list_voices(args.search, limit=args.limit)
        return doctor.run()

    if args.command == "fonts":
        from .fonts import install

        return install()

    if args.command == "audition":
        from .voices import audition

        audition(args.limit, log=_log)
        return 0

    if args.command == "init":
        from .runs import Run

        run = Run.create(args.topic)
        _log(str(run.directory))
        _log(f"\nWrite the storyboard to {run.storyboard_path}, then run `quinn-video check`.")
        return 0

    if args.command == "check":
        run = _resolve_run(args.run)
        board = run.storyboard()
        _log(f"topic:  {board.topic}")
        _log(f"beats:  {len(board.beats)}")
        _log(f"words:  {board.word_count}")
        _log(f"pacing: {board.pacing_note()}")
        if board.hook_variants:
            _log(f"hooks:  {len(board.hook_variants)} variants")

        manifest = board.render_manifest()
        if manifest:
            _log("\nwill render:")
            for note in manifest:
                _log(f"  {note}")

        from . import claims as claims_module

        issues = claims_module.audit(board)
        blockers = [i for i in issues if i.severity == "blocker"]
        if issues:
            _log("\nclaims:")
            for issue in issues:
                _log(f"  [{issue.severity:7}] {issue.detail}")
                _log(f"            {issue.fix}")
        elif board.claims:
            _log(f"\nclaims: {len(board.claims)} declared, all accounted for")

        if blockers:
            _log(
                "\nThe script asserts something the ledger does not cover. "
                "Nothing here checks whether a claim is true — the ledger is "
                "what puts it in front of a person who can."
            )
            return 2
        return 0

    if args.command == "plan":
        run = _resolve_run(args.run)
        _log(run.storyboard().review())
        return 0

    if args.command == "sources":
        from . import claims as claims_module

        run = _resolve_run(args.run)
        _log(claims_module.worklist(run.storyboard()))
        return 0

    if args.command == "narrate":
        from . import pipeline

        run = _resolve_run(args.run)
        pipeline.narrate(run, run.storyboard(), force=args.force, log=_log)
        return 0

    if args.command == "avatar":
        from . import pipeline

        run = _resolve_run(args.run)
        if args.collect:
            pipeline.collect_avatar(run, log=_log)
            return 0

        speech = pipeline.narrate(run, run.storyboard(), log=_log)
        if args.submit:
            pipeline.submit_avatar(run, speech, log=_log)
            return 0

        pipeline.render_avatar(run, speech, force=args.force, log=_log)
        return 0

    if args.command == "overlay":
        from . import pipeline

        run = _resolve_run(args.run)
        board = run.storyboard()
        speech = pipeline.narrate(run, board, log=_log)
        timings = pipeline.timings_for(board, speech, log=_log)
        pipeline.render_overlay(run, speech, timings, force=args.force, log=_log)
        return 0

    if args.command == "broll":
        from . import broll, pipeline

        run = _resolve_run(args.run)
        board = run.storyboard()
        speech = pipeline.narrate(run, board, log=_log)
        timings = pipeline.timings_for(board, speech, log=_log)

        broll.gather(run, board, per_query=args.per_query, log=_log)

        _log("\nBeat timings (shot lengths to fill):")
        for timing in timings:
            _log(
                f"  beat {timing.beat.id}: {timing.start:5.2f}-{timing.end:5.2f}s "
                f"({timing.duration:4.2f}s)  {timing.beat.visual.intent}"
            )
        _log(f"\nCandidates and thumbnails: {run.broll_dir}/candidates.json")
        _log("Review the thumbnails, then write picks.json and run `quinn-video fetch`.")
        return 0

    if args.command == "sheet":
        from . import broll

        run = _resolve_run(args.run)
        made = broll.contact_sheets(run, args.beat, log=_log)
        _log(f"\n{len(made)} sheet(s). Open each and score every candidate against the")
        _log("beat's narration — not against its visual intent, which you wrote.")
        return 0

    if args.command == "fetch":
        from . import broll, pipeline

        run = _resolve_run(args.run)
        path = Path(args.picks) if args.picks else run.directory / "picks.json"
        picks = json.loads(path.read_text(encoding="utf-8"))

        board = run.storyboard()
        by_id = {b.id: b for b in board.beats}

        # Generated graphics are cut to the length of their beat, so they need
        # the timeline. Narration is already paid for and cached.
        speech = pipeline.narrate(run, board, log=_log)
        beat_timings = pipeline.timings_for(board, speech, log=_log)
        spans = {t.beat.id: (t.start, t.duration) for t in beat_timings}

        # Resolve each beat's picks in the order they were written. Grouping
        # by source type instead would silently reorder the cut, putting every
        # generated shot after every stock one regardless of intent.
        from concurrent.futures import ThreadPoolExecutor

        cards: list[int] = []
        ai_beats: set[int] = set()
        jobs: list[tuple[int, int, dict]] = []

        for key, value in picks.items():
            beat_id = int(key)
            entries = value if isinstance(value, list) else [value]
            for slot, entry in enumerate(entries):
                if entry.get("card"):
                    cards.append(beat_id)
                elif entry.get("generate"):
                    ai_beats.add(beat_id)
                jobs.append((beat_id, slot, entry))

        def resolve(job: tuple[int, int, dict]) -> tuple[int, int, list[Path]]:
            beat_id, slot, entry = job
            window = spans.get(beat_id, (0.0, 4.0))
            words = [w for w in speech.words if window[0] <= w.start < window[0] + window[1]]
            if entry.get("card"):
                return (
                    beat_id,
                    slot,
                    [
                        broll.fallback_card(
                            run,
                            by_id[beat_id],
                            duration=window[1],
                            start=window[0],
                            words=words,
                            log=_log,
                        )
                    ],
                )
            if entry.get("generate"):
                prompt = entry["generate"]
                shot = broll.generate_shot(
                    run,
                    by_id[beat_id],
                    prompt if isinstance(prompt, str) else None,
                    variant=entry.get("variant"),
                    model=entry.get("model"),
                    log=_log,
                )
                if entry.get("annotate"):
                    shot = broll.annotate_shot(
                        run,
                        by_id[beat_id],
                        shot,
                        entry["annotate"],
                        duration=window[1],
                        start=window[0],
                        words=words,
                        log=_log,
                    )
                elif entry.get("animate"):
                    # The still already fixed the composition; this only adds
                    # movement to one that survived judging.
                    shot = broll.animate_shot(
                        run,
                        by_id[beat_id],
                        shot,
                        entry["animate"],
                        seconds=window[1],
                        log=_log,
                    )
                return beat_id, slot, [shot]
            return (
                beat_id,
                slot,
                list(broll.fetch_picks(run, {beat_id: [entry]}, log=_log).get(beat_id, [])),
            )

        # Every shot at once. Generation is ten seconds of waiting apiece, and
        # a fourteen-shot video spent over two minutes of a run doing them one
        # after another for no reason.
        with ThreadPoolExecutor(max_workers=6) as pool:
            done = list(pool.map(resolve, jobs))

        resolved: dict[int, list[Path]] = {}
        for beat_id, _slot, paths in sorted(done, key=lambda r: (r[0], r[1])):
            resolved.setdefault(beat_id, []).extend(paths)

        # An annotated diagram plays once; it must not be split into shots.
        cards = sorted(set(cards) | {b for b, _s, e in jobs if e.get("annotate")})

        run.update_state(
            picks={str(k): [str(p) for p in v] for k, v in sorted(resolved.items())},
            generated=sorted(cards),
            ai_generated=sorted(ai_beats),
        )
        shots = sum(len(v) for v in resolved.values())
        _log(f"\n{len(resolved)} of {len(board.beats)} beats have footage ({shots} clips).")
        return 0

    if args.command == "build":
        from . import pipeline

        run = _resolve_run(args.run)
        board = run.storyboard()
        speech = pipeline.narrate(run, board, log=_log)
        timings = pipeline.timings_for(board, speech, log=_log)
        pipeline.render_overlay(run, speech, timings, log=_log)

        picks = {
            int(k): [Path(p) for p in (v if isinstance(v, list) else [v])]
            for k, v in (run.state().get("picks") or {}).items()
        }
        if not picks:
            raise FileNotFoundError(
                "no footage selected for this run — run `quinn-video broll` then `fetch`"
            )

        music: Path | None = None
        if args.music == "auto":
            from .music import bed_prompt, generate_bed

            music = run.directory / "music.wav"
            prompt = bed_prompt(board.topic, args.mood)
            # A bed generated for a shorter script gets looped to fill the new
            # one, which is audible. Re-generate when the narration changes.
            key = cache.fingerprint(prompt, round(speech.duration, 1))
            if not cache.is_fresh(music, key):
                generate_bed(prompt, music, seconds=speech.duration, log=_log)
                cache.mark(music, key)
        elif args.music:
            music = Path(args.music)

        segments = pipeline.plan_segments(
            timings, picks, atomic=set(run.state().get("generated") or []), log=_log
        )
        pipeline.build(
            run,
            speech,
            segments,
            picks_index={
                str(path): int(beat_id)
                for beat_id, paths in (run.state().get("picks") or {}).items()
                for path in paths
            },
            music=music,
            force=args.force,
            log=_log,
        )
        return 0

    if args.command == "probe":
        from pathlib import Path as _Path

        from .config import require
        from .probe import probe_transparency

        result = probe_transparency(
            args.avatar or require("QUINN_AVATAR_ID", "the probe"),
            args.voice or require("QUINN_VOICE_ID", "the probe"),
            engine=args.engine,
            keep=_Path(args.keep) if args.keep else None,
            log=_log,
        )
        mark = "\033[32m✓\033[0m" if result.transparent else "\033[31m✗\033[0m"
        _log(f"\n{mark} transparent output: {result.detail}")
        _log(f"  {result.width}x{result.height}, {result.engine}, ~${result.cost:.2f} spent")
        if not result.transparent:
            _log("\n  Pick a different avatar, or render opaque and stage it as a")
            _log("  lower-third panel instead of a cutout.")
        return 0 if result.transparent else 1

    if args.command == "candidates":
        from . import broll

        run = _resolve_run(args.run)
        board = run.storyboard()
        by_id = {b.id: b for b in board.beats}
        picks = json.loads((run.directory / "picks.json").read_text(encoding="utf-8"))

        made: list[tuple[int, list[Path]]] = []
        for key, value in picks.items():
            beat_id = int(key)
            if args.beat and beat_id != args.beat:
                continue
            for entry in value if isinstance(value, list) else [value]:
                if not entry.get("generate"):
                    continue
                prompt = entry["generate"]
                paths = broll.generate_candidates(
                    run,
                    by_id[beat_id],
                    prompt if isinstance(prompt, str) else None,
                    count=args.count,
                    model=args.model,
                    log=_log,
                )
                made.append((beat_id, paths))

        _log("")
        for beat_id, paths in made:
            for path in paths:
                _log(f"  beat {beat_id}  {path.name}")
        _log("\nLook at every candidate. Reject any where the physical relationship is")
        _log("wrong — a ladder not touching what it leans on, a limb that does not bend")
        _log('the way an arm bends. Then set "variant": "b" on the pick and re-fetch.')
        return 0

    if args.command == "verify":
        from . import pipeline
        from . import verify as verifier

        run = _resolve_run(args.run)
        board = run.storyboard()
        speech = pipeline.narrate(run, board, log=_log)
        timings = pipeline.timings_for(board, speech, log=_log)

        reviews = verifier.collect(run, timings, speech.words, log=_log)
        verifier.write_manifest(run, reviews)
        sheet = verifier.contact_sheet(run, reviews)

        _log("")
        for r in reviews:
            _log(f"  {r.index:2d}  {r.start:5.1f}s  beat {r.beat_id}  {r.source[:34]:<34}")
            _log(f'      says: "{r.narration[:78]}"')
        _log(f"\ncontact sheet: {sheet}")
        _log("Look at each frame against the words spoken over it. A shot that does not")
        _log("serve its line is a miss even if it matches the beat's visual intent.")
        return 0

    if args.command == "grade":
        from . import grade as grader

        run = _resolve_run(args.run)
        report = grader.grade(run, log=_log)
        path = grader.write_report(run, report)

        _log(
            f"\n{report.duration:.1f}s  {report.width}x{report.height}  "
            f"{report.words} words  {report.wpm:.0f} wpm"
        )
        for finding in sorted(report.findings, key=lambda f: (f.severity != "blocker", f.at or 0)):
            at = "     " if finding.at is None else f"{finding.at:5.1f}"
            _log(f"  [{finding.severity:7}] {at}  {finding.criterion}: {finding.detail}")
        if not report.findings:
            _log("  nothing flagged mechanically")
        _log(f"\nscorecard: {path}")
        _log(
            "Now view the frames yourself and grade against the rubric — "
            "the mechanical pass cannot tell you whether it is engaging."
        )
        return 1 if report.blockers else 0

    if args.command == "status":
        run = _resolve_run(args.run)
        _log(f"run: {run.directory}")
        for label, path in [
            ("storyboard", run.storyboard_path),
            ("narration", run.audio),
            ("avatar", run.avatar),
            ("overlay", run.overlay),
            ("base", run.base),
            ("final", run.final),
            ("report", run.report),
        ]:
            mark = "✓" if run.has(path) else "·"
            size = f"{path.stat().st_size / 1e6:6.1f} MB" if run.has(path) else "        "
            _log(f"  {mark} {label:<11}{size}  {path.name}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
