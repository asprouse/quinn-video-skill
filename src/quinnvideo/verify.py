"""Pair every shot with the words spoken over it, for review.

The gap this closes: the b-roll gate judges a candidate against the beat's
`visual.intent`, and the intent is something *we* wrote. If the intent does
not serve the narration, every downstream check passes and the video still
shows the wrong thing. That is not a hypothetical -- a beat whose line was
"you don't have to be high up to die falling off a ladder" carried the intent
"a worker standing on a low stepladder", and the finished video contained no
danger at all. Nothing flagged it, because everything was consistent with the
intent.

So this compares shots against the *narration*, not against the intent, and
puts the two side by side so the mismatch is impossible to miss.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import ff
from .align import BeatTiming
from .heygen import Word
from .runs import Run


@dataclass
class ShotReview:
    index: int
    start: float
    duration: float
    source: str
    beat_id: int
    intent: str
    narration: str
    frame: Path


def collect(
    run: Run, timings: list[BeatTiming], words: list[Word], *, log=lambda _: None
) -> list[ShotReview]:
    """Grab one frame per shot and attach the words spoken across it."""
    state = run.state()
    segments = state.get("segments") or []
    if not segments:
        raise FileNotFoundError(
            "no shot list recorded for this run — run `quinn-video build` first"
        )

    by_beat = {t.beat.id: t for t in timings}
    directory = run.directory / "verify"
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("shot-*.jpg"):
        stale.unlink()

    reviews: list[ShotReview] = []
    for index, seg in enumerate(segments):
        start, duration = float(seg["start"]), float(seg["duration"])
        at = start + duration / 2
        frame = directory / f"shot-{index:02d}.jpg"
        ff.run(
            ["-ss", f"{at:.3f}", "-i", str(run.final), "-frames:v", "1",
             "-vf", "scale=360:640", "-q:v", "4", str(frame)]
        )

        spoken = " ".join(
            w.word for w in words if start <= w.start < start + duration
        ).strip()
        beat = by_beat.get(int(seg["beat"]))

        reviews.append(
            ShotReview(
                index=index,
                start=start,
                duration=duration,
                source=Path(seg["source"]).name,
                beat_id=int(seg["beat"]),
                intent=beat.beat.visual.intent if beat else "",
                narration=spoken or "(no words over this shot)",
                frame=frame,
            )
        )

    log(f"verify: {len(reviews)} shots sampled into {directory}")
    return reviews


def write_manifest(run: Run, reviews: list[ShotReview]) -> Path:
    """Write the pairing to disk so it can be read back and judged."""
    path = run.directory / "verify" / "shots.json"
    path.write_text(
        json.dumps(
            [
                {
                    "shot": r.index,
                    "at": round(r.start, 2),
                    "seconds": round(r.duration, 2),
                    "beat": r.beat_id,
                    "source": r.source,
                    "narration": r.narration,
                    "intent": r.intent,
                    "frame": str(r.frame),
                }
                for r in reviews
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def contact_sheet(run: Run, reviews: list[ShotReview], dest: Path | None = None) -> Path:
    """One image: every shot with the words spoken over it printed beneath."""
    from PIL import Image, ImageDraw

    from . import fonts

    dest = dest or run.directory / "verify" / "sheet.jpg"
    cols = min(4, max(1, len(reviews)))
    rows = (len(reviews) + cols - 1) // cols
    cw, ch, caption = 360, 640, 150

    sheet = Image.new("RGB", (cols * cw, rows * (ch + caption)), (16, 18, 22))
    draw = ImageDraw.Draw(sheet)
    label = fonts.load(fonts.CAPTION, 21)
    body = fonts.load(fonts.CAPTION, 19)

    for r in reviews:
        x, y = (r.index % cols) * cw, (r.index // cols) * (ch + caption)
        if r.frame.exists():
            with Image.open(r.frame) as frame:
                sheet.paste(frame.convert("RGB").resize((cw, ch)), (x, y))
        draw.text((x + 10, y + ch + 8), f"{r.index}  {r.start:.1f}s  beat {r.beat_id}",
                  font=label, fill=(255, 214, 0))
        for line_no, line in enumerate(_wrap(body, f"“{r.narration}”", cw - 24)[:4]):
            draw.text((x + 10, y + ch + 34 + line_no * 24), line, font=body,
                      fill=(232, 234, 240))

    sheet.save(dest, quality=86)
    return dest


def _wrap(font, text: str, limit: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if font.getlength(trial) > limit and line:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines
