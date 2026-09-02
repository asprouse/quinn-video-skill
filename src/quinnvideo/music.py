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
    "production, sits underneath a spoken voiceover."
)


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
    log(f"music: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
    return dest
