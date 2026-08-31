"""Preflight checks.

Runs before anything that costs money. Every paid call in this pipeline is
preceded by something that can fail for free -- a missing key, an ffmpeg
without the right codec, an absent font -- and finding those out three
minutes into an avatar render is a bad trade.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass

from . import config
from .config import Keys

OK = "\033[32m✓\033[0m"
WARN = "\033[33m!\033[0m"
FAIL = "\033[31m✗\033[0m"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fatal: bool = True  # a non-fatal failure degrades the pipeline, not blocks it

    @property
    def mark(self) -> str:
        if self.ok:
            return OK
        return FAIL if self.fatal else WARN

    def render(self) -> str:
        return f"  {self.mark} {self.name:<22} {self.detail}"


# --- individual checks ---------------------------------------------------


def check_ffmpeg() -> Iterable[Check]:
    binary = shutil.which("ffmpeg")
    if not binary:
        yield Check("ffmpeg", False, "not found — `brew install ffmpeg`")
        return

    version = subprocess.run(
        [binary, "-version"], capture_output=True, text=True, check=False
    ).stdout
    first = version.splitlines()[0].split(" Copyright")[0] if version else "unknown"
    yield Check("ffmpeg", True, first)

    # We composite an alpha WebM over b-roll, so VP9 decode is mandatory.
    decoders = subprocess.run(
        [binary, "-hide_banner", "-decoders"], capture_output=True, text=True, check=False
    ).stdout
    yield Check(
        "vp9 alpha decode",
        "vp9" in decoders,
        "available" if "vp9" in decoders else "missing — cannot composite the avatar",
    )

    yield Check(
        "h264 encode",
        "--enable-libx264" in version,
        "libx264" if "--enable-libx264" in version else "missing — cannot write final mp4",
    )

    # Captions are rendered by us into an RGBA layer rather than by libass, so
    # a bare Homebrew ffmpeg (which ships without libass or freetype) is fine.
    if "--enable-libass" not in version:
        yield Check(
            "libass",
            True,
            "absent — not needed, captions render via Pillow",
            fatal=False,
        )

    if not shutil.which("ffprobe"):
        yield Check("ffprobe", False, "not found — ships with ffmpeg")


def check_fonts() -> Iterable[Check]:
    if not config.FONTS.exists():
        yield Check("caption font", False, f"{config.FONTS} missing — run `quinn-video fonts`")
        return
    faces = sorted(p.name for p in config.FONTS.glob("*.ttf"))
    yield Check(
        "caption font",
        bool(faces),
        ", ".join(faces) if faces else "no .ttf in assets/fonts — run `quinn-video fonts`",
    )


def check_keys(keys: Keys) -> Iterable[Check]:
    yield Check(
        "HEYGEN_API_KEY",
        bool(keys.heygen),
        "set" if keys.heygen else "missing — required for narration and avatar",
    )
    yield Check(
        "PEXELS_API_KEY",
        bool(keys.pexels),
        "set" if keys.pexels else "missing — required for b-roll",
    )
    yield Check(
        "PIXABAY_API_KEY",
        bool(keys.pixabay),
        "set" if keys.pixabay else "unset — no secondary b-roll source",
        fatal=False,
    )
    generative = keys.fal or keys.replicate
    yield Check(
        "generative b-roll",
        bool(generative),
        "enabled" if generative else "unset — falls back to designed graphic cards",
        fatal=False,
    )


def check_heygen_live(keys: Keys) -> Iterable[Check]:
    """Confirm the key actually works, and that usable avatars/voices exist."""
    if not keys.heygen:
        return

    from .heygen import HeyGen, HeyGenError

    try:
        with HeyGen(keys.heygen) as client:
            avatars = client.avatars()
            ready = [a for a in avatars if a.get("status") in (None, "completed")]
            yield Check(
                "heygen avatars",
                bool(ready),
                f"{len(ready)} usable of {len(avatars)}"
                if ready
                else "none usable — create an avatar in the HeyGen dashboard",
            )

            voices = client.voices(engine="starfish")
            yield Check(
                "heygen voices",
                bool(voices),
                f"{len(voices)} starfish voices (word timestamps supported)"
                if voices
                else "no starfish voices — word-level captions impossible",
            )
    except HeyGenError as exc:
        yield Check("heygen api", False, str(exc).splitlines()[0])
    except Exception as exc:  # network, auth, anything else
        yield Check("heygen api", False, f"{type(exc).__name__}: {exc}")


def check_defaults(keys: Keys) -> Iterable[Check]:
    avatar = config.env("QUINN_AVATAR_ID")
    voice = config.env("QUINN_VOICE_ID")
    yield Check(
        "default avatar/voice",
        bool(avatar and voice),
        f"{avatar} / {voice}"
        if avatar and voice
        else "unset — pick with `quinn-video doctor --list-avatars`",
        fatal=False,
    )


# --- driver --------------------------------------------------------------


def run() -> int:
    keys = Keys.load()

    sections = [
        ("Rendering toolchain", list(check_ffmpeg()) + list(check_fonts())),
        ("Credentials", list(check_keys(keys))),
        ("HeyGen account", list(check_heygen_live(keys))),
        ("Defaults", list(check_defaults(keys))),
    ]

    print("\nquinn-video doctor\n")
    blockers = 0
    warnings = 0
    for title, checks in sections:
        if not checks:
            continue
        print(f"{title}")
        for check in checks:
            print(check.render())
            if not check.ok:
                if check.fatal:
                    blockers += 1
                else:
                    warnings += 1
        print()

    if blockers:
        print(f"{FAIL} {blockers} blocker(s). Fix these before rendering.\n")
        return 1
    if warnings:
        print(f"{WARN} Ready, with {warnings} degraded capability.\n")
    else:
        print(f"{OK} All systems go.\n")
    return 0


def list_avatars() -> int:
    """Print avatars as a pickable table. Transparent output needs a
    matting-trained avatar, and the API exposes no flag for that -- newer
    avatars have it, so we surface engine support as the best proxy."""
    from .heygen import HeyGen

    with HeyGen() as client:
        avatars = client.avatars()

    print(f"\n{len(avatars)} avatars\n")
    print(f"  {'id':<40} {'name':<26} {'orient':<10} {'engines'}")
    print(f"  {'-' * 40} {'-' * 26} {'-' * 10} {'-' * 20}")
    for avatar in avatars:
        engines = ",".join(
            e.replace("avatar_", "") for e in avatar.get("supported_api_engines") or []
        )
        print(
            f"  {(avatar.get('id') or '')[:40]:<40} "
            f"{(avatar.get('name') or '')[:26]:<26} "
            f"{(avatar.get('preferred_orientation') or '-'):<10} "
            f"{engines}"
        )
    print("\nPortrait avatars supporting avatar_iv/v are the best fit for 9:16.")
    print("Set QUINN_AVATAR_ID in .env to your pick.\n")
    return 0


def list_voices() -> int:
    from .heygen import HeyGen

    with HeyGen() as client:
        voices = client.voices(engine="starfish", language="en")

    print(f"\n{len(voices)} starfish voices (English)\n")
    for voice in voices:
        vid = voice.get("id") or voice.get("voice_id") or ""
        print(
            f"  {vid:<40} {(voice.get('name') or '')[:24]:<24} "
            f"{voice.get('gender') or '-':<8} {voice.get('language') or ''}"
        )
    print("\nSet QUINN_VOICE_ID in .env to your pick.\n")
    return 0
