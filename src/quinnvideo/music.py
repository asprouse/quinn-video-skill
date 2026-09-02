"""Generate a music bed for a run.

The compositor has always ducked a bed under the narration and nothing ever
supplied one, so every video so far has played over silence. For short-form
that is a large omission: a bed carries energy through the gaps between
sentences, which is exactly where attention leaks.

Generated rather than licensed, for the same reason the b-roll is: it can be
matched to the subject, and there is no licence to track for a video that may
be published anywhere.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import httpx

from .config import require

QUEUE = "https://queue.fal.run"
MODEL = "fal-ai/stable-audio"

# Instrumental, obviously — anything with a voice competes with the narrator.
# Steady rather than dramatic: a bed with its own arc pulls attention away
# from the one the script is building.
HOUSE_STYLE = (
    "Instrumental only, absolutely no vocals and no singing. Steady driving "
    "rhythm, consistent energy throughout, no big build or drop, clean "
    "production. Deep bass and low warm percussion carry the track; nothing "
    "bright, thin or hissy in the upper midrange. Sits underneath a spoken "
    "voiceover without competing with it."
)

# The bed is mixed under a voice, so what matters is where its energy sits,
# not whether it is pleasant on its own. A good bed puts most of itself below
# the voice; a bad one crowds the 2-6 kHz band the voice needs and reads as
# background noise. The generator ignores the prompt often enough that the
# compositor carves that band out regardless -- this is a check, not a filter.
VOICE_BAND = (2000.0, 6000.0)
VOICE_BAND_LIMIT = 0.25


class MusicError(RuntimeError):
    pass


def bed_prompt(topic: str, mood: str = "") -> str:
    return " ".join(
        p
        for p in (f"Background music bed for a short video about {topic}.", mood, HOUSE_STYLE)
        if p
    )


def generate_bed(
    prompt: str,
    dest: Path,
    *,
    seconds: float = 45.0,
    timeout: float = 600.0,
    log=lambda _: None,
) -> Path:
    """Generate an instrumental bed and save it."""
    key = require("FAL_KEY", "a generated music bed")
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}

    submit = httpx.post(
        f"{QUEUE}/{MODEL}",
        headers=headers,
        json={"prompt": prompt, "seconds_total": int(min(47, max(10, seconds + 3)))},
        timeout=120.0,
    )
    if submit.status_code != 200:
        raise MusicError(f"fal {MODEL} refused the job: {submit.text[:250]}")

    request_id = submit.json().get("request_id")
    base = f"{QUEUE}/{MODEL}/requests/{request_id}"
    log(f"music: queued {request_id}")

    started = time.monotonic()
    while time.monotonic() - started < timeout:
        status = httpx.get(f"{base}/status", headers=headers, timeout=60.0).json().get("status")
        if status == "COMPLETED":
            break
        if status == "FAILED":
            raise MusicError(f"fal {MODEL} failed")
        time.sleep(5.0)
    else:
        raise MusicError(f"fal {MODEL} still running after {timeout:.0f}s")

    result = httpx.get(base, headers=headers, timeout=60.0).json()
    url = (result.get("audio_file") or result.get("audio") or {}).get("url")
    if not url:
        raise MusicError(f"fal {MODEL} returned no audio: {str(result)[:250]}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(httpx.get(url, timeout=300.0).content)
    # Kept beside the audio so a bed that sounds wrong can be traced back to
    # what was asked for, the same way generated stills are.
    dest.with_suffix(".txt").write_text(prompt, encoding="utf-8")

    share = voice_band_share(dest)
    if share is not None and share > VOICE_BAND_LIMIT:
        log(
            f"music: warning — {share:.0%} of this bed sits in the "
            f"{VOICE_BAND[0]:.0f}-{VOICE_BAND[1]:.0f} Hz voice band; the mix "
            "will scoop it, but expect a thin bed"
        )
    log(f"music: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
    return dest


def voice_band_share(bed: Path) -> float | None:
    """Fraction of the bed's energy sitting in the band the voice needs.

    Returns None if the audio cannot be measured, which is not worth failing
    a render over -- the compositor carves the band out either way.
    """

    def rms_db(*filters: str) -> float | None:
        chain = ",".join(
            [
                *filters,
                "astats=metadata=1:reset=0",
                # astats only logs at info level; routing the value through
                # metadata puts it on stdout without the rest of the noise.
                "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
            ]
        )
        try:
            out = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-i",
                    str(bed),
                    "-ac",
                    "1",
                    "-af",
                    chain,
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        found = re.findall(r"RMS_level=(-?[\d.]+|-inf)", out)
        if not found:
            return None
        return float("-inf") if found[-1] == "-inf" else float(found[-1])

    total = rms_db("anull")
    inside = rms_db(
        f"bandpass=f={(VOICE_BAND[0] * VOICE_BAND[1]) ** 0.5:.0f}"
        f":width_type=h:w={VOICE_BAND[1] - VOICE_BAND[0]:.0f}"
    )
    if total is None or inside is None or total == float("-inf"):
        return None
    return min(1.0, 10 ** ((inside - total) / 10))
