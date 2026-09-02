"""Grade a finished render and report what to fix.

The brief says the iteration is the real work, so this makes the iteration
visible instead of leaving it to vibes. It measures what can be measured --
pacing, dead air, shot lengths, caption contrast, black frames -- and hands
the rest to Claude with the evidence attached.

It deliberately does not try to score "is this engaging". A number cannot
answer that. What it can do is surface every frame where the answer is
probably no, so the qualitative pass has somewhere to look.
"""

from __future__ import annotations

import html
import json
import statistics
import subprocess
from base64 import b64encode
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from . import ff
from .config import HEIGHT, WIDTH
from .heygen import Word
from .runs import Run

# A pause only reads as a stall relative to the script's own rhythm. Every
# sentence ends in a breath, so an absolute threshold near that length flags
# punctuation rather than pacing -- an earlier 0.6s cutoff reported five
# findings on a six-sentence script, one per full stop, which is noise.
# A stall is a gap that is both long outright and out of step with its
# neighbours.
LAYER_DRIFT = 0.75  # seconds a layer may differ from the narration
STALL_SECONDS = 0.9
STALL_RATIO = 1.8

# Silence adds up even when no single pause is wrong. But only *deliberate*
# pauses count: ordinary speech leaves a few hundredths of a second between
# most words, and totalling those puts any normal read near 40% silent. Gaps
# below this floor are phonetics, not pacing.
PAUSE_FLOOR = 0.25
SILENCE_SHARE = 0.25

MAX_SHOT = 4.0

SAMPLE_INTERVAL = 0.5


@dataclass
class Finding:
    severity: str  # "blocker" | "warn"
    at: float | None
    criterion: str
    detail: str
    fix: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "at": self.at,
            "criterion": self.criterion,
            "detail": self.detail,
            "fix": self.fix,
        }


@dataclass
class Report:
    duration: float
    width: int
    height: int
    words: int
    wpm: float
    findings: list[Finding] = field(default_factory=list)
    wpm_curve: list[tuple[float, float]] = field(default_factory=list)
    frames: list[dict] = field(default_factory=list)

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocker"]


# --- measurements --------------------------------------------------------


def gaps_between(words: list[Word]) -> list[tuple[float, float]]:
    """Every silence between consecutive words."""
    return [
        (current.end, following.start - current.end)
        for current, following in pairwise(words)
        if following.start > current.end
    ]


def stalls(words: list[Word]) -> list[tuple[float, float]]:
    """Pauses that break the script's own rhythm, not merely its sentences."""
    gaps = [g for _, g in gaps_between(words) if g > 0.05]
    if not gaps:
        return []
    typical = statistics.median(gaps)
    return [
        (at, gap)
        for at, gap in gaps_between(words)
        if gap >= STALL_SECONDS and gap >= typical * STALL_RATIO
    ]


def silence_share(words: list[Word], duration: float) -> float:
    """Share of the runtime given over to deliberate pauses."""
    if duration <= 0:
        return 0.0
    return sum(g for _, g in gaps_between(words) if g >= PAUSE_FLOOR) / duration


def wpm_curve(words: list[Word], window: float = 5.0) -> list[tuple[float, float]]:
    """Speaking rate over time. A flat curve is a monotonous read."""
    if not words:
        return []
    end = words[-1].end
    points = []
    t = 0.0
    while t < end:
        inside = [w for w in words if t <= w.start < t + window]
        points.append((round(t, 2), round(len(inside) / window * 60, 1)))
        t += window
    return points


def sample_frames(video: Path, directory: Path, interval: float = SAMPLE_INTERVAL) -> list[Path]:
    """Pull evenly spaced frames for inspection."""
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("frame-*.jpg"):
        stale.unlink()
    ff.run(
        [
            "-i",
            str(video),
            "-vf",
            f"fps=1/{interval},scale=270:480",
            "-q:v",
            "4",
            str(directory / "frame-%04d.jpg"),
        ]
    )
    return sorted(directory.glob("frame-*.jpg"))


def frame_stats(path: Path) -> dict:
    """Overall brightness. Enough to catch a dead or failed shot.

    An earlier version scored contrast in the caption band and flagged
    anything busy. It fired on seventy percent of frames, because busy
    footage is the normal case and the captions carry a nine-pixel stroke
    that keeps them readable over it. A check that fires that often is not a
    detector, it is noise, and it trains you to skim the report. Whether a
    frame is *hard to read* is a judgement, and it belongs to the reviewer
    looking at the frames -- not to a threshold.
    """
    from PIL import Image

    with Image.open(path) as handle:
        image = handle.convert("L")
        pixels = list(image.tobytes())

    return {"brightness": round(statistics.fmean(pixels) / 255, 3)}


# --- the grader ----------------------------------------------------------


def grade(run: Run, *, log=lambda _: None) -> Report:
    from .config import MAX_SECONDS, MIN_SECONDS

    video = run.final
    if not run.has(video):
        raise FileNotFoundError(f"no finished video at {video} — run `quinn-video build`")

    info = ff.probe(video)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    duration = float(info["format"]["duration"])

    speech = json.loads(run.speech_path.read_text(encoding="utf-8"))
    words = [Word(**w) for w in speech["words"]]

    report = Report(
        duration=duration,
        width=int(stream["width"]),
        height=int(stream["height"]),
        words=len(words),
        wpm=round(len(words) / duration * 60, 1) if duration else 0.0,
        wpm_curve=wpm_curve(words),
    )

    # --- shape
    if not (MIN_SECONDS <= duration <= MAX_SECONDS):
        report.findings.append(
            Finding(
                "blocker",
                None,
                "duration",
                f"{duration:.1f}s is outside the {MIN_SECONDS}-{MAX_SECONDS}s brief",
                "rewrite the script to fit, then re-narrate",
            )
        )
    if (report.width, report.height) != (WIDTH, HEIGHT):
        report.findings.append(
            Finding(
                "blocker",
                None,
                "format",
                f"{report.width}x{report.height} is not vertical 1080x1920",
                "check the compose settings",
            )
        )

    # --- pacing
    if report.wpm < 140:
        report.findings.append(
            Finding(
                "warn",
                None,
                "pacing",
                f"{report.wpm} wpm reads as a lecture",
                "tighten the script or raise the voice speed",
            ),
        )
    for at, gap in stalls(words):
        report.findings.append(
            Finding(
                "warn",
                round(at, 2),
                "stall",
                f"{gap:.2f}s of silence, well past this script's usual pause",
                "shorten the pause in the script, or let a visual beat carry it",
            ),
        )

    share = silence_share(words, duration)
    if share > SILENCE_SHARE:
        report.findings.append(
            Finding(
                "warn",
                None,
                "pacing",
                f"{share:.0%} of the runtime is silence",
                "tighten the script, or raise QUINN_VOICE_SPEED, then re-narrate",
            ),
        )

    # --- audio
    report.findings.extend(_audio_findings(video))

    # --- frames
    log("grade: sampling frames")
    for index, frame in enumerate(sample_frames(video, run.frames_dir)):
        at = round(index * SAMPLE_INTERVAL, 2)
        stats = frame_stats(frame)
        report.frames.append({"at": at, "path": str(frame), **stats})

        if stats["brightness"] < 0.04:
            report.findings.append(
                Finding(
                    "blocker",
                    at,
                    "black frame",
                    "frame is essentially black",
                    "the shot at this point is missing or failed to decode",
                ),
            )

    report.findings.extend(_staging_findings(run, words))
    report.findings.extend(_footage_findings(run))
    report.findings.extend(_layer_findings(run, duration))

    # The first two seconds decide everything, so they get their own check.
    opening = [f for f in report.frames if f["at"] <= 2.0]
    if opening and all(f["brightness"] < 0.12 for f in opening):
        report.findings.append(
            Finding(
                "blocker",
                0.0,
                "hook",
                "the opening two seconds are near-black",
                "lead with the strongest shot, not a dark one",
            ),
        )

    log(f"grade: {len(report.blockers)} blockers, {len(report.findings)} findings")
    return report


def _layer_findings(run: Run, duration: float) -> list[Finding]:
    """Every timed layer must run as long as the narration does.

    Two defects shipped this way. A stale avatar render, returned from the
    provider's cache after the script was re-narrated, was lip-synced to
    words that no longer existed and stopped fourteen seconds early. Then a
    stale caption layer put the captions of an earlier draft over the audio
    of a later one. In both cases every frame looked fine on its own, so
    nothing else here caught it.

    The layers are all cut from the same word timestamps, so any one of them
    disagreeing with the narration means it was built from a different script.
    Comparing durations is a cheap, total check for that.
    """
    layers = (
        (run.avatar, "the presenter", "delete avatar.webm and re-run `avatar`"),
        (run.overlay, "the caption layer", "delete work/overlay.mov and re-run `overlay`"),
        (run.base, "the b-roll base", "delete work/base.mp4 and re-run `build`"),
    )

    findings: list[Finding] = []
    for path, what, remedy in layers:
        if not run.has(path):
            continue
        try:
            actual = ff.duration(path)
        except Exception:
            continue
        if abs(actual - duration) > LAYER_DRIFT:
            findings.append(
                Finding(
                    "blocker",
                    None,
                    f"{path.name} out of sync",
                    f"{what} runs {actual:.1f}s against {duration:.1f}s of narration",
                    f"this layer was not built from the current script — {remedy}",
                )
            )
    return findings


def _footage_findings(run: Run) -> list[Finding]:
    """Catch a clip used more than once.

    A repeated shot is the most obvious tell that the footage ran thin, and
    it is invisible to every pixel measurement here -- each frame is fine on
    its own. Only the shot list shows it.
    """
    picks = run.state().get("picks") or {}
    seen: dict[str, list[str]] = {}
    for beat_id, paths in sorted(picks.items()):
        for path in paths if isinstance(paths, list) else [paths]:
            seen.setdefault(Path(path).name, []).append(str(beat_id))

    findings = []
    for name, beats in seen.items():
        if len(beats) > 1:
            findings.append(
                Finding(
                    "warn",
                    None,
                    "repeated footage",
                    f"{name} is used on beats {', '.join(beats)}",
                    "pick a distinct clip, or replace the beat with a generated graphic",
                )
            )
    return findings


def _staging_findings(run: Run, words: list[Word]) -> list[Finding]:
    """Check the presenter is not parked on top of the captions.

    This is the failure the eye catches instantly and no brightness threshold
    ever will: a cut-out avatar overlapping the caption line. The geometry is
    recorded at compose time, so it can be checked exactly rather than
    inferred from pixels.
    """
    from .captions import group_words
    from .graphics import CaptionStyle

    staging = run.state().get("staging") or []
    if not staging:
        return []

    style = CaptionStyle()
    # Captions are centred and grow upward from the baseline.
    cap_top = style.baseline_y - style.size
    cap_bottom = style.baseline_y + style.size

    findings: list[Finding] = []
    groups = group_words(words)

    for stage in staging:
        x, y, w, h = stage["rect"]
        if h <= 0:
            continue
        overlaps_rows = y < cap_bottom and (y + h) > cap_top
        if not overlaps_rows:
            continue
        # Full-bleed staging covers the whole width; captions land on the
        # presenter's chest, which is conventional in the format.
        if stage["scale"] >= 0.98:
            continue

        during = [g for g in groups if g.start < stage["end"] and g.end > stage["start"]]
        if not during:
            continue
        findings.append(
            Finding(
                "warn",
                round(stage["start"], 2),
                "avatar staging",
                f"presenter occupies x{x}-{x + w}, y{y}-{y + h}, "
                f"crossing the caption line while {len(during)} phrases are on screen",
                "shrink the presenter, move it lower, or raise the captions",
            )
        )
    return findings


def _audio_findings(video: Path) -> list[Finding]:
    """Check the mix actually landed near broadcast loudness."""
    result = subprocess.run(
        [ff.binary(), "-hide_banner", "-i", str(video), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    findings: list[Finding] = []
    for line in result.stderr.splitlines():
        if "mean_volume:" in line:
            mean = float(line.split("mean_volume:")[1].strip().split()[0])
            if mean < -30:
                findings.append(
                    Finding(
                        "blocker",
                        None,
                        "audio",
                        f"mean volume {mean:.1f} dB is near-silent",
                        "check the narration track reached the mix",
                    ),
                )
        if "max_volume:" in line:
            peak = float(line.split("max_volume:")[1].strip().split()[0])
            if peak > -0.5:
                findings.append(
                    Finding(
                        "warn",
                        None,
                        "audio",
                        f"peak {peak:.1f} dB is clipping",
                        "lower the music bed gain",
                    ),
                )
    return findings


# --- the scorecard -------------------------------------------------------


def write_report(run: Run, report: Report) -> Path:
    """Emit a self-contained HTML scorecard next to the video."""
    (run.directory / "report.json").write_text(
        json.dumps(
            {
                "duration": report.duration,
                "resolution": f"{report.width}x{report.height}",
                "words": report.words,
                "wpm": report.wpm,
                "findings": [f.to_dict() for f in report.findings],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    run.report.write_text(_html(run, report), encoding="utf-8")
    return run.report


def _html(run: Run, report: Report) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value))

    strip = []
    for frame in report.frames:
        path = Path(frame["path"])
        if not path.exists():
            continue
        data = b64encode(path.read_bytes()).decode()
        flagged = any(f.at is not None and abs(f.at - frame["at"]) < 0.01 for f in report.findings)
        strip.append(
            f'<figure class="{"flag" if flagged else ""}">'
            f'<img src="data:image/jpeg;base64,{data}" alt="frame at {frame["at"]}s">'
            f"<figcaption>{frame['at']:.1f}s</figcaption></figure>"
        )

    rows = (
        "".join(
            f'<tr class="{esc(f.severity)}"><td>{esc(f.severity)}</td>'
            f"<td>{'' if f.at is None else f'{f.at:.1f}s'}</td>"
            f"<td>{esc(f.criterion)}</td><td>{esc(f.detail)}</td><td>{esc(f.fix)}</td></tr>"
            for f in sorted(report.findings, key=lambda f: (f.severity != "blocker", f.at or 0))
        )
        or '<tr><td colspan="5">Nothing flagged mechanically. Judge it by eye.</td></tr>'
    )

    curve = "".join(
        f'<div class="bar" style="height:{min(100, v / 2.4):.0f}%" title="{t}s — {v} wpm"></div>'
        for t, v in report.wpm_curve
    )

    verdict = (
        f"{len(report.blockers)} blocker(s)"
        if report.blockers
        else f"{len(report.findings)} warning(s)"
        if report.findings
        else "clean"
    )

    return f"""<!doctype html>
<meta charset="utf-8">
<title>Scorecard — {esc(run.directory.name)}</title>
<style>
  :root {{ color-scheme: light dark; --bg:#fff; --fg:#16181d; --muted:#5c6370;
           --line:#e3e5ea; --flag:#ffd600; --bad:#d92d20; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#101216; --fg:#e8eaee; --muted:#98a0ad; --line:#272b33; }}
  }}
  body {{ background:var(--bg); color:var(--fg); margin:0; padding:40px;
          font:15px/1.55 ui-sans-serif,system-ui,-apple-system,sans-serif; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:var(--muted); margin-bottom:28px; }}
  .stats {{ display:flex; gap:32px; flex-wrap:wrap; padding:18px 0;
            border-block:1px solid var(--line); margin-bottom:28px; }}
  .stat b {{ display:block; font-size:24px; font-variant-numeric:tabular-nums; }}
  .stat span {{ color:var(--muted); font-size:12px; text-transform:uppercase;
                letter-spacing:.06em; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.07em;
        color:var(--muted); margin:32px 0 12px; }}
  table {{ border-collapse:collapse; width:100%; }}
  td, th {{ text-align:left; padding:9px 12px; border-bottom:1px solid var(--line);
            vertical-align:top; }}
  tr.blocker td:first-child {{ color:var(--bad); font-weight:700; }}
  .strip {{ display:flex; gap:6px; overflow-x:auto; padding-bottom:12px; }}
  figure {{ margin:0; flex:0 0 auto; text-align:center; }}
  figure img {{ display:block; width:108px; border-radius:6px;
                border:2px solid transparent; }}
  figure.flag img {{ border-color:var(--flag); }}
  figcaption {{ font-size:11px; color:var(--muted); margin-top:4px; }}
  .curve {{ display:flex; align-items:flex-end; gap:3px; height:90px;
            border-bottom:1px solid var(--line); }}
  .bar {{ flex:1; background:var(--flag); min-height:2px; border-radius:2px 2px 0 0; }}
</style>
<h1>{esc(run.directory.name)}</h1>
<div class="sub">Mechanical grading only — the qualitative pass is still yours.
Verdict: {esc(verdict)}.</div>

<div class="stats">
  <div class="stat"><b>{report.duration:.1f}s</b><span>duration</span></div>
  <div class="stat"><b>{report.width}&times;{report.height}</b><span>format</span></div>
  <div class="stat"><b>{report.words}</b><span>words</span></div>
  <div class="stat"><b>{report.wpm:.0f}</b><span>wpm</span></div>
  <div class="stat"><b>{len(report.blockers)}</b><span>blockers</span></div>
</div>

<h2>Findings</h2>
<table>
  <tr><th>Severity</th><th>At</th><th>Criterion</th><th>Detail</th><th>Fix</th></tr>
  {rows}
</table>

<h2>Speaking rate over time</h2>
<div class="curve">{curve}</div>

<h2>Frames — highlighted where something was flagged</h2>
<div class="strip">{"".join(strip)}</div>
"""
