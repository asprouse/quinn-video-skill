"""Generated b-roll, via fal.ai.

Stills rather than clips, deliberately. They cost a fraction of generated
video, the pipeline already gives stills a Ken Burns move, and they avoid the
morphing hands and warping rails that video models still produce -- which
matters more than usual here, because a viewer reads a safety video as
instruction.

What this is *for* is the finding that drove it: stock libraries have very
little genuine ladder-safety footage, and a generated ordinary scene beats a
loosely-related real one. What it is not for is procedure. Asking for an
unusual, precise pose -- a worker holding the toes-to-palms angle check --
returns something confidently wrong, or drops the person altogether. Those
beats belong to `diagrams`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import require

BASE = "https://fal.run"

# Cheap, fast and strong on ordinary photographic scenes.
DEFAULT_MODEL = "fal-ai/flux-pro/v1.1"
FAST_MODEL = "fal-ai/flux/schnell"

COST = {
    "fal-ai/flux/schnell": 0.025,
    "fal-ai/flux-pro/v1.1": 0.05,
    "fal-ai/bytedance/seedream/v4/text-to-image": 0.03,
}

# Appended to every prompt so a run's shots read as one shoot rather than a
# collection of stock. Without it the lighting and grade wander between beats.
HOUSE_STYLE = (
    "Documentary photograph, real workplace, natural daylight, photorealistic, "
    "sharp focus, muted colour grade, no text, no watermark."
)


class GenerationError(RuntimeError):
    pass


@dataclass
class Generated:
    path: Path
    prompt: str
    model: str
    cost: float
    seconds: float


def build_prompt(intent: str, extra: str = "") -> str:
    """Turn a beat's visual intent into a prompt.

    The intent is already a description of a shot, which is exactly what an
    image model wants -- so it carries over almost verbatim, with the house
    style appended for consistency across the run.
    """
    parts = [intent.strip().rstrip(".") + ".", extra.strip(), HOUSE_STYLE]
    return " ".join(p for p in parts if p)


def generate_still(
    prompt: str,
    dest: Path,
    *,
    model: str = DEFAULT_MODEL,
    width: int = 1080,
    height: int = 1920,
    timeout: float = 240.0,
) -> Generated:
    """Generate one image and save it."""
    key = require("FAL_KEY", "generated b-roll")
    started = time.monotonic()

    response = httpx.post(
        f"{BASE}/{model}",
        headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
        json={
            "prompt": prompt,
            "image_size": {"width": width, "height": height},
            "num_images": 1,
            "enable_safety_checker": True,
        },
        timeout=timeout,
    )
    if response.status_code != 200:
        raise GenerationError(f"fal {model} returned {response.status_code}: {response.text[:300]}")

    payload = response.json()
    images = payload.get("images") or []
    if not images or not images[0].get("url"):
        raise GenerationError(f"fal {model} returned no image: {str(payload)[:300]}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(httpx.get(images[0]["url"], timeout=timeout).content)

    return Generated(
        path=dest,
        prompt=prompt,
        model=model,
        cost=COST.get(model, 0.05),
        seconds=time.monotonic() - started,
    )
