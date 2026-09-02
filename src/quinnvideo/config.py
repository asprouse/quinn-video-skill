"""Environment, paths, and render constants.

Everything configurable lives here so the rest of the pipeline reads as prose.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --- Paths ---------------------------------------------------------------

# Where the code and its bundled assets live. Fixed, wherever the package was
# installed to.
PKG_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PKG_ROOT.parent.parent
ASSETS = REPO_ROOT / "assets"

# Typefaces are downloaded rather than committed, so an installed plugin
# arrives without them. They go in a user-level cache: the plugin directory is
# wiped on every update, and a per-project copy would re-download for each new
# video. Bundled copies in a development checkout win, so working on the repo
# needs no cache at all.
BUNDLED_FONTS = ASSETS / "fonts"
FONT_CACHE = Path(
    os.environ.get("QUINN_FONT_DIR") or Path.home() / ".cache" / "quinn-video" / "fonts"
)


def font_dir() -> Path:
    """Where typefaces are read from: the checkout if present, else the cache."""
    if BUNDLED_FONTS.exists() and any(BUNDLED_FONTS.glob("*.ttf")):
        return BUNDLED_FONTS
    return FONT_CACHE


# Where *this user's* work lives, which is a different question. Installed as
# a plugin the code sits under ~/.claude/plugins, and writing rendered video
# and API keys in there would be wrong twice over: the user cannot find them,
# and a reinstall would wipe them. Output belongs beside whatever project the
# person is standing in.
WORKSPACE = Path(os.environ.get("QUINN_WORKSPACE") or Path.cwd()).resolve()
RUNS = WORKSPACE / "runs"
CACHE = WORKSPACE / ".quinn-cache"


# --- Environment ---------------------------------------------------------
# Loaded before anything below reads os.environ, so .env can override the
# render defaults and not just the credentials.


def _load_dotenv() -> None:
    """Read .env into os.environ without clobbering real environment vars.

    The workspace copy wins. Installed as a plugin, the package directory is
    somewhere under ~/.claude that nobody is going to edit, so credentials
    have to be findable from where the user actually works. The package copy
    is only a fallback, for running out of a development checkout.

    Deliberately minimal: no python-dotenv dependency for a 10-line job.
    """
    candidates = [WORKSPACE / ".env", REPO_ROOT / ".env"]
    env_file = next((c for c in candidates if c.exists()), None)
    if env_file is None:
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

MIN_SECONDS = 30
MAX_SECONDS = 60

# The brief allows 30-60s. Avatar rendering is billed per second, so while
# iterating it is worth working at the short end and only stretching out once
# the script and the footage are settled.
TARGET_SECONDS = max(
    MIN_SECONDS, min(MAX_SECONDS, int(os.environ.get("QUINN_TARGET_SECONDS") or 45))
)

# Delivery speed passed to HeyGen.
#
# This was 0.85 for a long time and it was wrong. The original calibration
# used a twenty-four word fragment, which came back at 258 wpm and looked like
# auctioneer speed -- but a fragment has almost no sentence pauses, so it
# wildly overstates the rate. Real scripts at 0.85 landed at 145 to 178 wpm,
# and 145 is well under the floor where a read starts to drag.
#
# Measured properly across six voices on a script-shaped line, speed 1.0 lands
# between 167 and 180 wpm, which is the band short-form wants. Calibrate on
# something the length of a real script or the number lies to you.
VOICE_SPEED = float(os.environ.get("QUINN_VOICE_SPEED") or 1.0)

# The band a short-form read wants to sit in. Below the floor it drags; above
# the ceiling it stops being punchy and starts being hard to follow, which
# costs comprehension on a video whose whole job is to teach something.
#
# No single speed setting hits this band for every script: the same 1.0 gave
# 170 wpm on one and 197 on another, because sentence length and punctuation
# density move the rate as much as the setting does. So narrate measures what
# it got and says what to change.
SLOW_WPM = 158
FAST_WPM = 188

# Passed to HeyGen with every avatar render. Measured against the same audio
# and the same avatar, this lifts frame-to-frame movement by about a quarter --
# the difference between a head that talks and a person who is presenting.
# Costs nothing; it is a field on a render already being paid for.
MOTION_PROMPT = os.environ.get("QUINN_MOTION_PROMPT") or (
    "Energetic, confident delivery. Animated hand gestures, leaning slightly "
    "toward the camera, expressive eyebrows, natural head movement."
)

# Longest a single shot holds before cutting. Every second here is an asset
# not sourced, not judged and not paid for, so it is the cheapest lever in the
# pipeline -- bounded by how long a shot can hold before it reads as static.
MAX_SHOT = float(os.environ.get("QUINN_MAX_SHOT") or 7.0)

# Measured, not assumed. Two full scripts through the configured voice at
# VOICE_SPEED came back at 178 and 165 wpm, so 170 is the honest figure; the
# earlier 198 came from a single short line and made `check` underestimate
# runtimes by around a fifth. It is only an estimate either way -- the real
# duration arrives with the narration.
TARGET_WPM = int(os.environ.get("QUINN_TARGET_WPM") or 170)


def words_for(seconds: float = TARGET_SECONDS) -> int:
    return int(seconds * TARGET_WPM / 60)


# --- Environment ---------------------------------------------------------


class ConfigError(RuntimeError):
    """A required key or setting is missing."""


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
