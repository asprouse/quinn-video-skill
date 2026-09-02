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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import require

BASE = "https://fal.run"

# Ultra renders around 1536x2752 and is downsampled into the 1080x1920 canvas,
# which is why it holds detail the others lose. Plain flux-pro/v1.1 is
# deliberately absent: it ignores the requested size and returns 1056x1440,
# so every frame arrived as a heavy crop upscaled by a third.
DEFAULT_MODEL = "fal-ai/flux-pro/v1.1-ultra"
ALT_MODEL = "fal-ai/bytedance/seedream/v4/text-to-image"
FAST_MODEL = "fal-ai/flux/schnell"

COST = {
    "fal-ai/flux/schnell": 0.025,
    "fal-ai/flux/dev": 0.025,
    "fal-ai/flux-pro/v1.1-ultra": 0.06,
    "fal-ai/bytedance/seedream/v4/text-to-image": 0.03,
}

# Models that take an aspect ratio string rather than explicit pixel dimensions.
ASPECT_MODELS = {"fal-ai/flux-pro/v1.1-ultra"}

# Appended to every prompt so a run's shots read as one shoot rather than a
# collection of stock. Without it the lighting, lens and grade wander between
# beats, which is the single clearest tell that footage was assembled rather
# than shot.
HOUSE_STYLE = (
    "Shot on a 35mm lens at eye level, overcast natural daylight, muted "
    "desaturated colour grade, documentary photograph of a real workplace, "
    "photorealistic, sharp focus, no text, no watermark, no logos."
)

# A recurring subject does more for continuity than any amount of grading.
# Without it every beat casts a different worker on a different site.
DEFAULT_SUBJECT = (
    "The same worker throughout: a man in his thirties wearing a yellow hi-vis "
    "vest over a navy long-sleeved shirt, a white hard hat, and grey work trousers."
)


def _borders_are_flat(data: bytes, tolerance: int = 6, dark: int = 40) -> str | None:
    """Detect letterboxing: uniform *dark* bars across the top and bottom.

    Image models occasionally return a composed frame with bars baked in, and
    cropping to fill then hands the compositor dead space nobody notices.

    Uniformity alone is not enough to go on: a plain concrete wall or an
    overcast sky is perfectly flat across a row and entirely legitimate. A
    letterbox bar is flat *and* dark *and* markedly darker than the middle of
    the picture, so all three are required before rejecting a frame.
    """
    import io
    import statistics

    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        grey = image.convert("L")
        w, h = grey.size

        def band(y0: int, y1: int) -> tuple[float, float]:
            pixels = list(grey.crop((0, y0, w, y1)).tobytes())
            return statistics.fmean(pixels), statistics.pstdev(pixels)

        top_mean, top_sd = band(0, max(2, h // 40))
        bottom_mean, bottom_sd = band(h - max(2, h // 40), h)
        middle_mean, _ = band(h // 2 - h // 40, h // 2 + h // 40)

    for name, mean, sd in (("top", top_mean, top_sd), ("bottom", bottom_mean, bottom_sd)):
        if sd < tolerance and mean < dark and mean < middle_mean - 40:
            return f"a flat dark bar runs across the {name} of the frame — it looks letterboxed"
    return None


class GenerationError(RuntimeError):
    pass


class PromptBlockedError(GenerationError):
    """The provider's safety filter refused the prompt."""


def _reject_if_bad(data: bytes, model: str, width: int, height: int) -> None:
    """Refuse anything that would degrade or blank the shot."""
    import statistics

    from PIL import Image

    got_w, got_h = _dimensions(data)

    import io

    with Image.open(io.BytesIO(data)) as image:
        pixels = list(image.convert("L").tobytes())
    mean = statistics.fmean(pixels)
    spread = statistics.pstdev(pixels)

    # A uniform black frame is what fal returns when the safety checker blocks
    # a prompt. It arrives at an off-size too, so check this first and give
    # the real reason rather than a confusing complaint about resolution.
    if mean < 2 and spread < 2:
        raise PromptBlockedError(
            f"{model} returned a blank frame — the prompt was almost certainly refused "
            "by the safety filter. Describe the hazard rather than the injury: "
            '"overreaching", "off balance", "the ladder tipping" rather than falling or harm.'
        )

    if got_w < width or got_h < height:
        raise GenerationError(
            f"{model} returned {got_w}x{got_h}, smaller than the {width}x{height} canvas. "
            "It would be upscaled. Use a model that honours the requested size."
        )

    defect = _borders_are_flat(data)
    if defect:
        raise GenerationError(f"{model}: {defect}. Re-run to draw a different frame.")


def _dimensions(data: bytes) -> tuple[int, int]:
    import io

    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        return image.size


@dataclass
class Generated:
    path: Path
    prompt: str
    model: str
    cost: float
    seconds: float


def build_prompt(intent: str, extra: str = "", *, subject: str = DEFAULT_SUBJECT) -> str:
    """Turn a beat's visual intent into a prompt.

    The intent is already a description of a shot, which is exactly what an
    image model wants, so it carries over almost verbatim -- with the subject
    and house style appended so every shot in a run looks like the same
    photographer followed the same worker around one site.
    """
    parts = [intent.strip().rstrip(".") + ".", extra.strip(), subject, HOUSE_STYLE]
    return " ".join(p for p in parts if p)


def generate_candidates(
    prompt: str,
    directory: Path,
    stem: str,
    *,
    count: int = 3,
    model: str = DEFAULT_MODEL,
    log=lambda _: None,
) -> list[Path]:
    """Draw the same prompt several times and keep every frame that passes.

    A single draw is a lottery. Testing one prompt across models and seeds,
    the same wording produced a ladder correctly resting on a wall, a ladder
    floating in front of one, and a ladder standing bolt upright. No amount of
    prompt wording removes that variance -- the fix is to draw a few and
    choose, which is what a photographer does anyway.
    """

    def draw(index: int) -> Path | None:
        letter = chr(ord("a") + index)
        dest = directory / f"{stem}-{letter}.jpg"
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        try:
            generate_still(prompt, dest, model=model, attempts=1)
            log(f"    candidate {letter}: ok")
        except GenerationError as exc:
            log(f"    candidate {letter}: rejected — {str(exc).split(chr(46))[0][:70]}")
            return None
        return dest

    # Independent draws of the same prompt, so there is no reason to wait for
    # one before starting the next.
    with ThreadPoolExecutor(max_workers=min(count, 4)) as pool:
        return [p for p in pool.map(draw, range(count)) if p is not None]


def generate_still(
    prompt: str,
    dest: Path,
    *,
    model: str = DEFAULT_MODEL,
    width: int = 1080,
    height: int = 1920,
    timeout: float = 240.0,
    attempts: int = 3,
) -> Generated:
    """Generate one image and save it.

    Retries on a rejected frame: the safety filter and the occasional
    letterboxed composition are both non-deterministic, and a second draw of
    the same prompt usually comes back clean.
    """
    last: GenerationError | None = None
    for _ in range(attempts):
        try:
            return _attempt(prompt, dest, model, width, height, timeout)
        except GenerationError as exc:
            last = exc
    raise last if last else GenerationError("generation failed")


def _attempt(
    prompt: str, dest: Path, model: str, width: int, height: int, timeout: float
) -> Generated:
    key = require("FAL_KEY", "generated b-roll")
    started = time.monotonic()

    size: dict = (
        {"aspect_ratio": "9:16"}
        if model in ASPECT_MODELS
        else {"image_size": {"width": width, "height": height}}
    )
    response = httpx.post(
        f"{BASE}/{model}",
        headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
        json={"prompt": prompt, "num_images": 1, "enable_safety_checker": True, **size},
        timeout=timeout,
    )
    if response.status_code != 200:
        raise GenerationError(f"fal {model} returned {response.status_code}: {response.text[:300]}")

    payload = response.json()
    images = payload.get("images") or []
    if not images or not images[0].get("url"):
        raise GenerationError(f"fal {model} returned no image: {str(payload)[:300]}")

    data = httpx.get(images[0]["url"], timeout=timeout).content

    # Validate *before* writing. An earlier version wrote first and raised
    # after, which left the rejected frame on disk where the next run picked
    # it up as a valid cache hit -- so a blocked, entirely black placeholder
    # shipped into the video.
    _reject_if_bad(data, model, width, height)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    return Generated(
        path=dest,
        prompt=prompt,
        model=model,
        cost=COST.get(model, 0.05),
        seconds=time.monotonic() - started,
    )
