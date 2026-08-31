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

    sub.add_parser("fonts", help="download the bundled caption typefaces")

    init = sub.add_parser("init", help="create a run directory for a topic")
    init.add_argument("topic")

    check = sub.add_parser("check", help="validate a storyboard and report its pacing")
    check.add_argument("--run")

    with_run(sub.add_parser("narrate", help="synthesise the voiceover (costs credits)"))
    with_run(sub.add_parser("avatar", help="render the presenter (costs credits)"))
    with_run(sub.add_parser("overlay", help="draw the caption layer"))

    gather = with_run(sub.add_parser("broll", help="search stock footage for every beat"))
    gather.add_argument("--per-query", type=int, default=8)

    fetch = with_run(sub.add_parser("fetch", help="download the chosen footage"))
    fetch.add_argument("--picks", help="picks JSON (default: <run>/picks.json)")

    build = with_run(sub.add_parser("build", help="composite the finished video"))
    build.add_argument("--music", help="optional music bed")

    with_run(sub.add_parser("grade", help="score the finished video and write a scorecard"))
    with_run(sub.add_parser("status", help="show what a run has produced so far"))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
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
        from . import doctor

        if args.list_avatars:
            return doctor.list_avatars()
        if args.list_voices:
            return doctor.list_voices()
        return doctor.run()

    if args.command == "fonts":
        from .fonts import install

        return install()

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
            _log(f"hooks:  {len(board.hook_variants)} variants awaiting selection")
        return 0

    if args.command == "narrate":
        from . import pipeline

        run = _resolve_run(args.run)
        pipeline.narrate(run, run.storyboard(), force=args.force, log=_log)
        return 0

    if args.command == "avatar":
        from . import pipeline

        run = _resolve_run(args.run)
        speech = pipeline.narrate(run, run.storyboard(), log=_log)
        pipeline.render_avatar(run, speech, force=args.force, log=_log)
        return 0

    if args.command == "overlay":
        from . import pipeline

        run = _resolve_run(args.run)
        speech = pipeline.narrate(run, run.storyboard(), log=_log)
        pipeline.render_overlay(run, speech, force=args.force, log=_log)
        return 0

    if args.command == "broll":
        from . import broll, pipeline

        run = _resolve_run(args.run)
        board = run.storyboard()
        speech = pipeline.narrate(run, board, log=_log)
        timings = pipeline.timings_for(run, board, speech, log=_log)

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

    if args.command == "fetch":
        from . import broll

        run = _resolve_run(args.run)
        path = Path(args.picks) if args.picks else run.directory / "picks.json"
        picks = json.loads(path.read_text(encoding="utf-8"))

        board = run.storyboard()
        by_id = {b.id: b for b in board.beats}

        real = {int(k): v for k, v in picks.items() if not v.get("card")}
        resolved = broll.fetch_picks(run, real, log=_log) if real else {}

        for key, value in picks.items():
            if value.get("card"):
                resolved[int(key)] = broll.fallback_card(run, by_id[int(key)], log=_log)

        run.update_state(picks={str(k): str(v) for k, v in resolved.items()})
        _log(f"\n{len(resolved)} of {len(board.beats)} beats have footage.")
        return 0

    if args.command == "build":
        from . import pipeline

        run = _resolve_run(args.run)
        board = run.storyboard()
        speech = pipeline.narrate(run, board, log=_log)
        timings = pipeline.timings_for(run, board, speech, log=_log)
        pipeline.render_overlay(run, speech, log=_log)

        picks = {int(k): Path(v) for k, v in (run.state().get("picks") or {}).items()}
        if not picks:
            raise FileNotFoundError(
                "no footage selected for this run — run `quinn-video broll` then `fetch`"
            )

        segments = pipeline.plan_segments(timings, picks, log=_log)
        pipeline.build(
            run,
            speech,
            segments,
            music=Path(args.music) if args.music else None,
            force=args.force,
            log=_log,
        )
        return 0

    if args.command == "grade":
        from . import grade as grader

        run = _resolve_run(args.run)
        report = grader.grade(run, log=_log)
        path = grader.write_report(run, report)

        _log(f"\n{report.duration:.1f}s  {report.width}x{report.height}  "
             f"{report.words} words  {report.wpm:.0f} wpm")
        for finding in sorted(report.findings, key=lambda f: (f.severity != "blocker", f.at or 0)):
            at = "     " if finding.at is None else f"{finding.at:5.1f}"
            _log(f"  [{finding.severity:7}] {at}  {finding.criterion}: {finding.detail}")
        if not report.findings:
            _log("  nothing flagged mechanically")
        _log(f"\nscorecard: {path}")
        _log("Now view the frames yourself and grade against the rubric — "
             "the mechanical pass cannot tell you whether it is engaging.")
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
