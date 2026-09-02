"""Audition voices by measurement, not by guesswork.

There are four hundred English voices on this account and no way to listen to
them all. Three things separate an engaging read from a lethargic one, and all
three are measurable:

  rate      words per minute
  dynamics  how far the loudness moves — a monotone read is flat, an emphatic
            one swings between stressed and unstressed syllables
  attack    how sharply loudness rises at word onsets, which is what makes a
            delivery sound punchy rather than smooth

This narrows four hundred to a handful. A person still picks the winner by
ear, which is why every audition is written to disk.

Two things the first version of this got wrong, both worth not repeating.
Audition on a *script-shaped* line: a short fragment has almost no sentence
pauses, so it overstates the rate and ranks voices in nearly the opposite
order. And compare at a *matched* rate, or a voice scores well merely for
talking fast, which says nothing about whether it is alive.
"""

from __future__ import annotations

import statistics
import struct
import subprocess
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from .config import CACHE, TARGET_WPM
from .heygen import HeyGen, download

# Long enough that sentence pauses do not dominate, and shaped like a real
# script: a hook, a turn, and a payload with a number in it.
AUDITION_LINE = (
    "Which is faster: a Nissan Skyline GT-R, or a Toyota Supra? Wrong question. "
    "Ask where. Give them corners and it is the GT-R, because its all wheel drive "
    "throws power forward the moment the rears break loose. Now straighten the "
    "track. The Supra's iron block straight six swallows boost that grenades "
    "other engines."
)


@dataclass
class Reading:
    name: str
    voice_id: str
    speed: float
    wpm: float
    dynamics: float
    attack: float
    path: Path

    @property
    def liveliness(self) -> float:
        """How much the delivery moves, once rate is held constant."""
        return self.dynamics * 0.7 + self.attack * 0.3


def _envelope(path: Path, window_ms: int = 40) -> list[float]:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    samples = struct.unpack(f"<{len(raw) // 2}h", raw[: len(raw) // 2 * 2])
    step = 16000 * window_ms // 1000
    return [
        (sum(s * s for s in samples[i : i + step]) / step) ** 0.5
        for i in range(0, len(samples) - step, step)
    ]


def _measure(name, voice_id, speed, path, words, seconds) -> Reading:
    env = [e for e in _envelope(path) if e > 0]
    loud = [e for e in env if e > max(env) * 0.08]  # ignore the silences
    dynamics = statistics.pstdev(loud) / statistics.fmean(loud) if len(loud) > 2 else 0.0
    rises = [max(0.0, b - a) for a, b in pairwise(env)]
    attack = (
        statistics.fmean(sorted(rises)[-max(1, len(rises) // 8) :]) / max(env) if rises else 0.0
    )
    return Reading(
        name, voice_id, speed, len(words) / seconds * 60 if seconds else 0, dynamics, attack, path
    )


def audition(limit: int = 24, *, target: float = TARGET_WPM, log=print) -> list[Reading]:
    """Read the same line in `limit` voices, each driven to the target rate."""
    directory = CACHE / "auditions"
    directory.mkdir(parents=True, exist_ok=True)

    with HeyGen() as client:
        pool = [
            v
            for v in client.voices(engine="starfish", language="en", max_items=400)
            if (v.get("name") or "").strip()
        ][:limit]

        readings: list[Reading] = []
        for voice in pool:
            vid = voice.get("id") or voice.get("voice_id")
            name = (voice.get("name") or vid)[:28]
            speed, reading = 1.0, None
            # Two probes: rate is close to linear in speed across this range.
            for _ in range(2):
                speed = round(min(2.0, max(0.5, speed)), 2)
                try:
                    speech = client.speech(AUDITION_LINE, vid, speed=speed)
                except Exception as exc:
                    log(f"  {name:28} skipped — {str(exc)[:44]}")
                    break
                dest = directory / f"{vid}-{speed:.2f}.mp3"
                download(speech.audio_url, dest)
                reading = _measure(name, vid, speed, dest, speech.words, speech.duration)
                if abs(reading.wpm - target) < 6:
                    break
                speed *= target / max(reading.wpm, 1)
            if reading:
                readings.append(reading)
                log(
                    f"  {name:28} speed {reading.speed:4.2f} -> {reading.wpm:5.0f} wpm   "
                    f"dyn {reading.dynamics:.3f}  atk {reading.attack:.3f}"
                )

    readings.sort(key=lambda r: -r.liveliness)
    log(f"\nMost alive at ~{target:.0f} wpm:")
    for r in readings[:6]:
        log(f"  {r.liveliness:.3f}  {r.name:28} speed {r.speed:4.2f}  {r.voice_id}")
    log(f"\nSamples in {directory} — listen before deciding. The numbers only")
    log("narrow the field; they cannot tell you whether a voice suits the subject.")
    return readings
