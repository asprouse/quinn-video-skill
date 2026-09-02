"""Turn a vetted still into a moving shot.

The order matters. Generating video directly means judging a clip you cannot
easily re-frame; generating a still first means the composition is settled
cheaply, on something you can look at in a contact sheet, before any motion is
paid for. Only the shots that survive that pass get animated.

A Ken Burns move is a pan across a photograph. This is the subject actually
moving — a worker climbing rather than a photograph of a worker drifting
sideways — and on a hero shot the difference is the whole difference.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import require

QUEUE = "https://queue.fal.run"

# Turbo tier: image-to-video at a fraction of the flagship price, and the
# input still already fixes the composition, so the model has far less to get
# wrong than it would from a text prompt alone.
DEFAULT_MODEL = "fal-ai/kling-video/v2.5-turbo/pro/image-to-video"

# Kling accepts discrete lengths, not arbitrary ones. A shot longer than the
# clip is looped by the compositor, which is invisible on a slow move.
LENGTHS = (5, 10)

POLL_INTERVAL = 5.0
TIMEOUT = 600.0


class AnimationError(RuntimeError):
    pass


@dataclass
class Animated:
    path: Path
    seconds: int
    prompt: str
    took: float


def motion_prompt(intent: str, extra: str = "") -> str:
    """A motion instruction, not a scene description.

    The still already establishes what is in frame. Describing the subject
    again invites the model to re-imagine it; describing only the movement
    keeps the composition that was approved.
    """
    parts = [
        extra.strip() or "Gentle, natural movement.",
        f"The scene is: {intent.strip().rstrip('.')}.",
        "Slow deliberate camera push. Keep the framing and the subject as they are. "
        "No cuts, no new objects entering frame, no text.",
    ]
    return " ".join(p for p in parts if p)


def _length_for(seconds: float) -> int:
    """Nearest supported clip length that covers the shot without waste."""
    return next((option for option in LENGTHS if option >= seconds - 0.4), LENGTHS[-1])


def animate(
    image: Path,
    dest: Path,
    prompt: str,
    *,
    seconds: float = 5.0,
    model: str = DEFAULT_MODEL,
    log=lambda _: None,
) -> Animated:
    """Animate one still and save the clip."""
    key = require("FAL_KEY", "animated b-roll")
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    length = _length_for(seconds)
    started = time.monotonic()

    # Inlined rather than uploaded: it saves a round trip and a second place
    # for the file to go stale.
    encoded = base64.b64encode(image.read_bytes()).decode()

    submit = httpx.post(
        f"{QUEUE}/{model}",
        headers=headers,
        json={
            "prompt": prompt,
            "image_url": f"data:image/jpeg;base64,{encoded}",
            "duration": str(length),
        },
        timeout=180.0,
    )
    if submit.status_code != 200:
        raise AnimationError(f"fal {model} refused the job: {submit.text[:300]}")

    log(f"animate: queued {length}s from {image.name}")
    request_id = submit.json().get("request_id")
    if not request_id:
        raise AnimationError(f"fal {model} returned no request id: {submit.text[:200]}")

    # The queue endpoints hang off the model family, not the full model path.
    family = "/".join(model.split("/")[:2])
    base = f"{QUEUE}/{family}/requests/{request_id}"

    while time.monotonic() - started < TIMEOUT:
        state = httpx.get(f"{base}/status", headers=headers, timeout=60.0).json()
        status = state.get("status")
        if status == "COMPLETED":
            break
        if status == "FAILED":
            raise AnimationError(f"fal {model} failed: {str(state)[:300]}")
        time.sleep(POLL_INTERVAL)
    else:
        raise AnimationError(f"fal {model} still running after {TIMEOUT:.0f}s")

    result = httpx.get(base, headers=headers, timeout=60.0).json()
    url = (result.get("video") or {}).get("url")
    if not url:
        raise AnimationError(f"fal {model} returned no video: {str(result)[:300]}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(httpx.get(url, timeout=600.0).content)

    return Animated(
        path=dest,
        seconds=length,
        prompt=prompt,
        took=time.monotonic() - started,
    )
