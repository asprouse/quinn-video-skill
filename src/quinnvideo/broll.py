"""Sourcing on-topic footage.

The brief's hardest requirement is negative: "Nothing random or unrelated."
Stock search cannot deliver that on its own -- searching "ladder safety"
returns handshakes and generic office footage alongside the real thing.

So the split here is deliberate. This module *finds and presents* candidates
with their thumbnails; judging them is Claude's job, because judging whether
a picture shows what a sentence describes is exactly the kind of thing a
search API cannot do and a model can. What comes back is a decision, not a
ranking, and if nothing clears the bar the fallback ladder ends in a designed
card rather than a shrug.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from . import graphics
from .runs import Run
from .stock import Candidate, Kind, Stock
from .storyboard import Beat, Storyboard

Log = Callable[[str], None]

# Enough to saturate a home connection without hammering either provider.
WORKERS = 8


def _noop(_: str) -> None:
    return None


def gather(
    run: Run,
    board: Storyboard,
    *,
    per_query: int = 8,
    log: Log = _noop,
) -> dict[str, Any]:
    """Search every beat's queries and cache the thumbnails for inspection.

    Writes ``candidates.json`` and a thumbnail per candidate. Nothing is
    downloaded at full size yet -- that happens only for what gets picked.
    """
    thumbs = run.broll_dir / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {"beats": []}

    with Stock() as stock:

        def search(beat: Beat, query: str, kind: Kind) -> list[Candidate]:
            try:
                return stock.search(query, kind, limit=per_query)
            except Exception as exc:
                log(f"beat {beat.id}: search '{query}' failed — {exc}")
                return []

        # Every search across every beat at once. They are independent HTTP
        # calls; running them one at a time was tens of seconds of waiting for
        # no reason.
        jobs = [(b, q, b.visual.prefer) for b in board.beats for q in b.visual.queries]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(lambda job: search(*job), jobs))

        by_beat: dict[int, list[Candidate]] = {b.id: [] for b in board.beats}
        seen_per_beat: dict[int, set[str]] = {b.id: set() for b in board.beats}
        for (beat, _, _), hits in zip(jobs, results, strict=True):
            for hit in hits:
                key = f"{hit.provider}:{hit.ident}"
                if key not in seen_per_beat[beat.id]:
                    seen_per_beat[beat.id].add(key)
                    by_beat[beat.id].append(hit)

        # A beat that wanted video and got almost nothing falls back to stills:
        # a strong photograph with a Ken Burns move beats a weak video.
        thin = [
            (b, q, "photo")
            for b in board.beats
            if len(by_beat[b.id]) < 3 and b.visual.prefer == "video"
            for q in b.visual.queries[:2]
        ]
        if thin:
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                for (beat, _, _), hits in zip(
                    thin, pool.map(lambda job: search(*job), thin), strict=True
                ):
                    for hit in hits:
                        key = f"{hit.provider}:{hit.ident}"
                        if key not in seen_per_beat[beat.id]:
                            seen_per_beat[beat.id].add(key)
                            by_beat[beat.id].append(hit)

        # Thumbnails likewise: a hundred-odd small downloads, all independent.
        every = [c for b in board.beats for c in by_beat[b.id]]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            downloaded = list(pool.map(lambda c: _cache_thumb(c, thumbs), every))
        # Keyed by identity, not by the candidate itself: Candidate is a plain
        # mutable dataclass and therefore unhashable.
        fetched = {(c.provider, c.ident): path for c, path in zip(every, downloaded, strict=True)}

        for beat in board.beats:
            found = by_beat[beat.id]
            entries = [
                {
                    **asdict(candidate),
                    "thumbnail": (
                        str(fetched[(candidate.provider, candidate.ident)])
                        if fetched.get((candidate.provider, candidate.ident))
                        else None
                    ),
                    "vertical": candidate.is_vertical,
                }
                for candidate in found
            ]

            log(f"beat {beat.id}: {len(entries)} candidates for '{beat.visual.intent}'")
            manifest["beats"].append(
                {
                    "id": beat.id,
                    "narration": beat.narration,
                    "intent": beat.visual.intent,
                    "queries": beat.visual.queries,
                    "candidates": entries,
                }
            )

    path = run.broll_dir / "candidates.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _cache_thumb(candidate: Candidate, directory: Path) -> Path | None:
    if not candidate.preview_url:
        return None
    dest = directory / f"{candidate.provider}-{candidate.ident}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        response = httpx.get(candidate.preview_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        dest.write_bytes(response.content)
    except Exception:
        # A thumbnail that will not download costs us one candidate, not the
        # run. The gate simply has one fewer option to look at.
        return None
    return dest


def contact_sheets(run: Run, beat_id: int | None = None, *, log: Log = _noop) -> list[Path]:
    """Render one labelled contact sheet per beat, for judging by eye.

    The gate depends on somebody actually looking at every candidate, and
    opening a hundred thumbnails one at a time is not that. A sheet per beat,
    numbered, is -- and building it here rather than improvising the code each
    run keeps the numbering stable enough to refer to.
    """
    import math

    from PIL import Image, ImageDraw

    from . import fonts

    manifest = json.loads((run.broll_dir / "candidates.json").read_text(encoding="utf-8"))
    directory = run.broll_dir / "sheets"
    directory.mkdir(parents=True, exist_ok=True)

    label = fonts.load(fonts.CAPTION, 20)
    made: list[Path] = []
    cols, cw, ch, caption = 5, 300, 200, 28

    for beat in manifest["beats"]:
        if beat_id is not None and beat["id"] != beat_id:
            continue
        cands = [c for c in beat["candidates"] if c.get("thumbnail")]
        if not cands:
            continue

        rows = math.ceil(len(cands) / cols)
        sheet = Image.new("RGB", (cols * cw, rows * (ch + caption)), (18, 20, 24))
        draw = ImageDraw.Draw(sheet)

        for index, candidate in enumerate(cands):
            x, y = (index % cols) * cw, (index // cols) * (ch + caption)
            try:
                with Image.open(candidate["thumbnail"]) as raw:
                    thumb = raw.convert("RGB")
                    scale = max(cw / thumb.width, ch / thumb.height)
                    thumb = thumb.resize((round(thumb.width * scale), round(thumb.height * scale)))
                    sheet.paste(thumb.crop((0, 0, cw, ch)), (x, y))
            except Exception:
                draw.text((x + 8, y + 8), "no thumbnail", font=label, fill=(200, 80, 80))
            draw.text(
                (x + 6, y + ch + 5),
                f"{index + 1}. {candidate['ident']} {candidate['kind'][:3]}",
                font=label,
                fill=(235, 235, 240),
            )

        dest = directory / f"beat-{beat['id']}.jpg"
        sheet.save(dest, quality=85)
        made.append(dest)
        log(f"beat {beat['id']}: {len(cands)} candidates -> {dest}")

    return made


def fetch_picks(
    run: Run, picks: dict[int, list[dict[str, str]]], *, log: Log = _noop
) -> dict[int, list[Path]]:
    """Download the full-size asset for every accepted candidate.

    ``picks`` maps a beat id to a list of ``{"provider":..., "ident":...}``
    entries chosen from the candidate manifest. Several per beat is normal:
    long beats need more than one shot to stay alive.
    """
    manifest = json.loads((run.broll_dir / "candidates.json").read_text(encoding="utf-8"))
    # Keyed globally, not per beat. The same clip often surfaces under several
    # beats' searches, and a reviewer who spots the right shot while reviewing
    # one beat should be able to use it on any of them.
    lookup = {(c["provider"], c["ident"]): c for b in manifest["beats"] for c in b["candidates"]}

    resolved: dict[int, list[Path]] = {}
    with Stock() as stock:
        for beat_id, chosen in picks.items():
            for pick in chosen:
                entry = lookup.get((pick["provider"], pick["ident"]))
                if not entry:
                    log(f"beat {beat_id}: {pick} is in no beat's candidate list")
                    continue
                candidate = Candidate(
                    **{k: v for k, v in entry.items() if k not in ("thumbnail", "vertical")}
                )
                resolved.setdefault(int(beat_id), []).append(stock.fetch(candidate, run.broll_dir))
                log(f"beat {beat_id}: {candidate.filename()}")

    return resolved


def generate_candidates(
    run: Run,
    beat: Beat,
    prompt: str | None,
    *,
    count: int = 3,
    model: str | None = None,
    log: Log = _noop,
) -> list[Path]:
    """Draw several options for one shot, for a human to choose between."""
    import hashlib

    from .generate import DEFAULT_MODEL, build_prompt
    from .generate import generate_candidates as draw

    text = prompt or build_prompt(beat.visual.intent)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    directory = run.broll_dir / "candidates"
    directory.mkdir(parents=True, exist_ok=True)

    log(f"beat {beat.id}: drawing {count} candidates — {text[:60]}...")
    paths = draw(
        text,
        directory,
        f"beat-{beat.id}-{digest}",
        count=count,
        model=model or DEFAULT_MODEL,
        log=log,
    )
    (directory / f"beat-{beat.id}-{digest}.txt").write_text(text, encoding="utf-8")
    return paths


def generate_shot(
    run: Run,
    beat: Beat,
    prompt: str | None = None,
    *,
    variant: str | None = None,
    model: str | None = None,
    log: Log = _noop,
) -> Path:
    """Generate this beat's b-roll rather than sourcing it.

    Reached when stock has nothing honest, or chosen outright for a beat whose
    scene is easy to describe and hard to find. Not for procedures -- see the
    note in `generate`.
    """
    import hashlib

    from .generate import DEFAULT_MODEL, build_prompt, generate_still

    text = prompt or build_prompt(beat.visual.intent)

    # Keyed on the prompt, not on position. A beat may carry several generated
    # shots, and indexing by position means editing a prompt silently returns
    # the image the old one produced.
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]

    # A chosen candidate wins: it was picked by eye from several draws.
    if variant:
        chosen = run.broll_dir / "candidates" / f"beat-{beat.id}-{digest}-{variant}.jpg"
        if not chosen.exists():
            raise FileNotFoundError(
                f"beat {beat.id}: candidate '{variant}' not found at {chosen}. "
                "Run `quinn-video candidates` first, then choose one."
            )
        return chosen

    dest = run.broll_dir / f"generated-beat-{beat.id}-{digest}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    log(f"beat {beat.id}: generating — {text[:70]}...")
    result = generate_still(text, dest, model=model or DEFAULT_MODEL)
    log(f"beat {beat.id}: generated in {result.seconds:.1f}s (${result.cost:.3f})")

    # Kept beside the image so a reviewer can see what was asked for, and
    # judge the result against it rather than against the narration alone.
    dest.with_suffix(".txt").write_text(text, encoding="utf-8")
    return dest


def animate_shot(
    run: Run,
    beat: Beat,
    still: Path,
    spec: object,
    *,
    seconds: float = 5.0,
    log: Log = _noop,
) -> Path:
    """Give a chosen still real motion.

    Only reached for stills that already survived the judging pass, so the
    money is spent moving a composition somebody approved rather than rolling
    the dice on one.
    """
    from .animate import animate, motion_prompt

    dest = run.broll_dir / f"animated-{still.stem}.mp4"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    prompt = motion_prompt(beat.visual.intent, spec if isinstance(spec, str) else "")
    result = animate(still, dest, prompt, seconds=seconds, log=log)
    log(f"beat {beat.id}: animated {still.name} -> {result.seconds}s in {result.took:.0f}s")
    return dest


def annotate_shot(
    run: Run,
    beat: Beat,
    photo: Path,
    spec: dict,
    *,
    duration: float = 4.0,
    words: list | None = None,
    start: float = 0.0,
    log: Log = _noop,
) -> Path:
    """Draw the rule onto a real photograph instead of onto a black card.

    The anchors in ``spec`` are read off the image by eye and written into
    picks.json. They cannot be detected reliably, and a wrong anchor would
    draw a confident annotation in the wrong place -- so the renderer checks
    the geometry they imply and refuses if it does not match the rule being
    taught.
    """
    from .diagrams import render_ladder_annotation

    # Anchors are measured against one specific image. Generation is not
    # deterministic, so pin them: if the photograph changed, the coordinates
    # are stale and would draw the rule somewhere it does not belong. The
    # ratio check in the renderer cannot catch this -- it validates the
    # anchors against each other, not against the picture.
    stamp = photo.stem.rsplit("-", 1)[-1]
    expected = spec.get("for_image")
    if expected and expected != stamp:
        raise ValueError(
            f"beat {beat.id}: anchors were measured on image {expected}, but the "
            f"photograph is now {stamp}. Re-read the ladder's base and top off the "
            "new image and update picks.json."
        )
    if not expected:
        log(f'beat {beat.id}: anchors are not pinned — add "for_image": "{stamp}"')

    dest = run.broll_dir / f"annotated-beat-{beat.id}-{stamp}.mp4"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    cues = _diagram_cues(beat, words or [], start, duration)
    ratio = tuple(spec.get("ratio", [4, 1]))
    log(f"beat {beat.id}: annotating {photo.name} with the {ratio[0]}:{ratio[1]} rule")
    render_ladder_annotation(
        photo,
        dest,
        duration,
        base=tuple(spec["base"]),
        top=tuple(spec["top"]),
        ratio=ratio,
        cues=cues,
    )
    return dest


def fallback_card(
    run: Run,
    beat: Beat,
    *,
    duration: float = 4.0,
    words: list | None = None,
    start: float = 0.0,
    log: Log = _noop,
) -> Path:
    """Generate this beat's graphic: an animated diagram, or a designed card."""
    if beat.overlay and beat.overlay.kind == "ladder-angle":
        from .diagrams import render_ladder_angle

        dest = run.broll_dir / f"diagram-beat-{beat.id}.mp4"
        if not (dest.exists() and dest.stat().st_size > 0):
            cues = _diagram_cues(beat, words or [], start, duration)
            log(
                f"beat {beat.id}: drawing the {beat.overlay.ratio[0]}:"
                f"{beat.overlay.ratio[1]} diagram ({duration:.1f}s), "
                + ", ".join(f"{k} @{v:.2f}s" for k, v in sorted(cues.items()))
            )
            render_ladder_angle(dest, duration, ratio=beat.overlay.ratio, cues=cues)
        return dest

    dest = run.broll_dir / f"card-beat-{beat.id}.jpg"
    # The overlay text is authored for the screen; the headline falls back to
    # the narration. visual.intent is a search instruction and must never
    # appear -- it reads as debug output leaking into the video.
    text = beat.overlay.text if beat.overlay else _headline(beat)
    kicker = "the rule" if beat.overlay and beat.overlay.kind == "rule" else ""
    graphics.render_card(text, dest, kicker=kicker)
    log(f"beat {beat.id}: no footage cleared the bar — designed card instead")
    return dest


def _diagram_cues(beat: Beat, words: list, start: float, duration: float) -> dict[str, float]:
    """Anchor the drawing's phases to the words that name them.

    Without this the diagram runs to its own clock and annotates the ratio
    seconds before the narration says it, which reads as the graphic and the
    voice talking past each other.
    """
    from .align import normalise

    spoken = [(normalise(w.word), w.start - start) for w in words]
    number_words = {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
    }
    up, out = beat.overlay.ratio if beat.overlay else (4, 1)

    def find(target: str, after: float = -1.0) -> float | None:
        for token, at in spoken:
            if token == target and at > after:
                return at
        return None

    # The ratio is usually spoken last ("...it's four to one"), and "one" often
    # occurs earlier in the sentence too, so the run is searched after the rise.
    rise = find(number_words.get(up, str(up)))
    run = find(number_words.get(out, str(out)), after=rise if rise is not None else -1.0)
    ladder = find("base") or find("ladder")

    cues: dict[str, float] = {"structure": 0.15}
    if ladder is not None:
        cues["ladder"] = max(0.4, ladder - 0.5)
    if rise is not None:
        cues["rise"] = max(cues.get("ladder", 0.4) + 0.3, rise - 0.25)
    if run is not None:
        cues["run"] = max(cues.get("rise", 1.0) + 0.25, run - 0.2)

    # Leave the finished drawing on screen rather than resolving at the buzzer.
    for key in ("rise", "run"):
        if key in cues:
            cues[key] = min(cues[key], duration - 0.7)
    return cues


def _headline(beat: Beat) -> str:
    """Pull a short headline out of the narration for a fallback card."""
    if beat.emphasis:
        return " ".join(beat.emphasis[:4])
    words = beat.narration.replace(",", "").split()
    return " ".join(words[:6])
