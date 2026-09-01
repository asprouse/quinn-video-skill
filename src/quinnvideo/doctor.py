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
    directory = config.font_dir()
    if not directory.exists():
        yield Check("caption font", False, "none found — run `quinn-video fonts`")
        return
    faces = sorted(p.name for p in directory.glob("*.ttf"))
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
    yield Check(
        "generative b-roll",
        bool(keys.fal),
        "fal.ai enabled — ~$0.05 per generated still"
        if keys.fal
        else "unset — falls back to designed graphic cards",
        fatal=False,
    )


def check_heygen_live(keys: Keys) -> Iterable[Check]:
    """Confirm the key works and that the configured avatar and voice exist.

    Deliberately does not enumerate the catalogue. HeyGen's public library runs
    to roughly ten thousand avatars and two thousand voices, and walking it
    turned this preflight into a two-minute wait.
    """
    if not keys.heygen:
        return

    from .heygen import HeyGen, HeyGenError

    try:
        with HeyGen(keys.heygen) as client:
            # One page is enough to prove the key authenticates.
            page = client.avatars(max_items=1)
            yield Check("heygen api", bool(page), "authenticated" if page else "no avatars visible")

            # Avatar rendering is the only expensive step, and running out of
            # balance mid-pipeline wastes the narration already paid for.
            from .heygen import estimate_cost

            balance = client.balance()
            if balance is not None:
                per_render = estimate_cost(config.TARGET_SECONDS)
                affordable = int(balance // per_render) if per_render else 0
                yield Check(
                    "heygen balance",
                    affordable >= 1,
                    f"${balance:.2f} — about {affordable} render(s) of "
                    f"{config.TARGET_SECONDS}s at ${per_render:.2f} each",
                )

            avatar_id = config.env("QUINN_AVATAR_ID")
            if avatar_id:
                looked_up = client.avatar(avatar_id)
                engines = ",".join(
                    e.replace("avatar_", "")
                    for e in (looked_up or {}).get("supported_api_engines") or []
                )
                yield Check(
                    "configured avatar",
                    bool(looked_up),
                    f"{(looked_up or {}).get('name', '?')} ({engines})"
                    if looked_up
                    else f"{avatar_id} not found on this account",
                )

            voice_id = config.env("QUINN_VOICE_ID")
            if voice_id:
                # The speech endpoint only accepts starfish voices, and only
                # starfish returns the word timestamps everything downstream
                # is timed against.
                match = next(
                    (
                        v
                        for v in client.voices(engine="starfish", max_items=400)
                        if (v.get("id") or v.get("voice_id")) == voice_id
                    ),
                    None,
                )
                yield Check(
                    "configured voice",
                    bool(match),
                    f"{match.get('name', '?')} — starfish, word timestamps supported"
                    if match
                    else f"{voice_id} is not a starfish voice — captions cannot be timed",
                )
    except HeyGenError as exc:
        yield Check("heygen api", False, str(exc).splitlines()[0])
    except Exception as exc:  # network, auth, anything else
        yield Check("heygen api", False, f"{type(exc).__name__}: {exc}")


def check_defaults() -> Iterable[Check]:
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
        ("Defaults", list(check_defaults())),
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


def list_avatars(search: str | None = None, *, limit: int = 40) -> int:
    """Print a shortlist of avatars worth using for a vertical video.

    HeyGen exposes roughly ten thousand avatars, most of them landscape studio
    presenters that would be cropped to pieces at 9:16. This filters to
    portrait looks on the newer engines and stops at a readable number, rather
    than printing a catalogue nobody will read.

    Transparent output additionally needs a matting-trained avatar, and no
    field advertises that. Newer engines are the best available proxy, so
    avatar_v and avatar_iv looks are listed first.
    """
    mine, pool = _avatar_catalogue()

    def usable(a: dict) -> bool:
        if a.get("status") not in (None, "completed"):
            return False
        return not (search and search.lower() not in (a.get("name") or "").lower())

    def rank(a: dict) -> tuple:
        engines = a.get("supported_api_engines") or []
        return (
            0 if a.get("id") in {m.get("id") for m in mine} else 1,
            0 if "avatar_v" in engines else 1 if "avatar_iv" in engines else 2,
            0 if a.get("preferred_orientation") == "portrait" else 1,
            (a.get("name") or "").lower(),
        )

    own_ids = {m.get("id") for m in mine}
    shortlist = sorted((a for a in pool if usable(a)), key=rank)[:limit]

    print(f"\n{len(shortlist)} shown ({len(mine)} on your account)\n")
    print(f"  {'':2} {'id':<38} {'name':<26} {'orient':<9} {'engines'}")
    print(f"  {'':2} {'-' * 38} {'-' * 26} {'-' * 9} {'-' * 18}")
    for avatar in shortlist:
        engines = ",".join(
            e.replace("avatar_", "") for e in avatar.get("supported_api_engines") or []
        )
        mark = "*" if avatar.get("id") in own_ids else " "
        print(
            f"  {mark:2} {(avatar.get('id') or '')[:38]:<38} "
            f"{(avatar.get('name') or '')[:26]:<26} "
            f"{(avatar.get('preferred_orientation') or '-'):<9} "
            f"{engines}"
        )
    print("\n  * = on your account. Portrait looks are listed first: they are")
    print("  natively 1080x1920, so nothing is cropped away at 9:16.")
    print("  Set QUINN_AVATAR_ID in .env to your pick.\n")
    return 0


def _avatar_catalogue(scan: int = 4000, ttl_hours: int = 24) -> tuple[list[dict], list[dict]]:
    """Fetch (and cache) enough of the avatar catalogue to choose from.

    HeyGen paginates fifty at a time and the public library runs to five
    figures, so a full scan is dozens of round trips. Portrait looks -- the
    ones that need no cropping at 9:16 -- are scattered deep in it, so we have
    to go reasonably far in and then keep what we found.
    """
    import json
    import time

    from .heygen import HeyGen

    cache = config.CACHE / "avatars.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < ttl_hours * 3600:
        stored = json.loads(cache.read_text(encoding="utf-8"))
        return stored["mine"], stored["pool"]

    with HeyGen() as client:
        mine = client.avatars(ownership="private", max_items=100)
        pool = list(mine) + client.avatars(ownership="public", max_items=scan)

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"mine": mine, "pool": pool}), encoding="utf-8")
    return mine, pool


def list_voices(search: str | None = None, *, limit: int = 40) -> int:
    """Print starfish voices -- the only engine that returns word timestamps."""
    from .heygen import HeyGen

    with HeyGen() as client:
        voices = client.voices(engine="starfish", language="en", max_items=600)

    if search:
        voices = [v for v in voices if search.lower() in (v.get("name") or "").lower()]

    shown = voices[:limit]
    print(f"\n{len(shown)} shown of {len(voices)} English starfish voices\n")
    for voice in shown:
        vid = voice.get("id") or voice.get("voice_id") or ""
        print(
            f"  {vid:<40} {(voice.get('name') or '')[:24]:<24} "
            f"{voice.get('gender') or '-':<8} {voice.get('language') or ''}"
        )
    print("\n  Only starfish voices return word-level timestamps, which the")
    print("  captions and b-roll cuts are both timed against.")
    print("  Set QUINN_VOICE_ID in .env to your pick.\n")
    return 0
