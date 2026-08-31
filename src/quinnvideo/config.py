"""Environment, paths, and render constants.

Everything configurable lives here so the rest of the pipeline reads as prose.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --- Paths ---------------------------------------------------------------

PKG_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PKG_ROOT.parent.parent
ASSETS = REPO_ROOT / "assets"
FONTS = ASSETS / "fonts"
RUNS = REPO_ROOT / "runs"


# --- Canvas --------------------------------------------------------------
# Vertical 9:16, the only shape that matters for TikTok/Reels/Shorts.

WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Platform chrome eats the edges of the frame. Nothing readable goes here.
# Measured against TikTok, which is the most aggressive of the three.
SAFE_BOTTOM = 340  # caption bar, username, description
SAFE_TOP = 120  # "Following / For You" tabs
SAFE_RIGHT = 200  # like/comment/share rail


# --- Pacing --------------------------------------------------------------
# The brief asks for 30-60s. We aim mid-range: long enough to teach one idea,
# short enough that nobody swipes.

TARGET_SECONDS = 45
MIN_SECONDS = 30
MAX_SECONDS = 60

# Short-form narration runs fast. Below ~140 wpm it feels like a lecture.
TARGET_WPM = 165
WORDS_FOR_TARGET = int(TARGET_SECONDS * TARGET_WPM / 60)


# --- Environment ---------------------------------------------------------


class ConfigError(RuntimeError):
    """A required key or setting is missing."""


def _load_dotenv() -> None:
    """Read .env into os.environ without clobbering real environment vars.

    Deliberately minimal: no python-dotenv dependency for a 10-line job.
    """
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value.strip() if value else None


def require(name: str, why: str) -> str:
    value = env(name)
    if not value:
        raise ConfigError(f"{name} is not set. Needed for {why}. See .env.example.")
    return value


@dataclass(frozen=True)
class Keys:
    heygen: str | None
    pexels: str | None
    pixabay: str | None
    fal: str | None
    replicate: str | None

    @classmethod
    def load(cls) -> Keys:
        return cls(
            heygen=env("HEYGEN_API_KEY"),
            pexels=env("PEXELS_API_KEY"),
            pixabay=env("PIXABAY_API_KEY"),
            fal=env("FAL_KEY"),
            replicate=env("REPLICATE_API_TOKEN"),
        )
