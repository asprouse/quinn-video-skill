"""Screening for frames that must never reach the compositor."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from quinnvideo.generate import (
    GenerationError,
    PromptBlockedError,
    _borders_are_flat,
    _reject_if_bad,
    build_prompt,
)


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def _photo(width: int = 1080, height: int = 1920) -> Image.Image:
    """A plausible frame: mid-grey with texture, so it is not flat anywhere."""
    image = Image.new("RGB", (width, height), (128, 128, 128))
    for y in range(0, height, 3):
        for x in range(0, width, 3):
            image.putpixel((x, y), (90 + (x + y) % 90, 120, 150))
    return image


def test_a_blank_frame_is_reported_as_a_blocked_prompt():
    """fal returns solid black when its safety filter refuses a prompt.

    One shipped into a finished video, so this is the check that matters most.
    """
    with pytest.raises(PromptBlockedError, match="safety filter"):
        _reject_if_bad(_jpeg(Image.new("RGB", (1024, 768))), "m", 1080, 1920)


def test_an_undersized_frame_is_refused():
    """Anything below the canvas would be upscaled, which is the softness the
    whole module exists to avoid."""
    with pytest.raises(GenerationError, match="smaller than"):
        _reject_if_bad(_jpeg(_photo(600, 1000)), "m", 1080, 1920)


def test_a_good_frame_passes():
    _reject_if_bad(_jpeg(_photo()), "m", 1080, 1920)


def test_letterboxing_is_detected():
    image = _photo()
    for y in list(range(90)) + list(range(1920 - 90, 1920)):
        for x in range(1080):
            image.putpixel((x, y), (0, 0, 0))

    assert _borders_are_flat(_jpeg(image))


def test_a_plain_wall_is_not_letterboxing():
    """Regression: a flat, bright concrete wall was being rejected as a bar.

    Uniformity alone is not the signal — a bar is also dark, and darker than
    the middle of the picture.
    """
    image = _photo()
    for y in list(range(90)) + list(range(1920 - 90, 1920)):
        for x in range(1080):
            image.putpixel((x, y), (210, 210, 208))

    assert _borders_are_flat(_jpeg(image)) is None


def test_prompts_carry_the_subject_and_house_style():
    prompt = build_prompt("a worker on a ladder")

    assert prompt.startswith("a worker on a ladder.")
    assert "hi-vis" in prompt  # recurring subject, for continuity
    assert "35mm" in prompt  # house style, so shots match
    assert "no watermark" in prompt
