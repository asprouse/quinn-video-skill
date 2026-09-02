"""Preflight checks.

Runs before anything that costs money. Every paid call in this pipeline is
preceded by something that can fail for free -- a missing key, an ffmpeg
without the right codec, an absent font -- and finding those out three
minutes into an avatar render is a bad trade.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

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


# --- preflight -----------------------------------------------------------

# What each stage actually needs. Checking only the relevant capability means
# `build` does not demand a HeyGen key it will never use, and `narrate` does
# not demand ffmpeg.
NEEDS: dict[str, tuple[str, ...]] = {
    # init checks the whole pipeline, not its own needs. There is no point
    # starting a run that cannot finish, and finding out after the script is
    # written wastes the one thing a preflight is supposed to protect: the
    # user's time. `--draft` bypasses it for writing offline.
    "init": ("ffmpeg", "fonts", "heygen", "pexels"),
    "narrate": ("heygen",),
    "avatar": ("heygen",),
    "probe": ("heygen",),
    "overlay": ("ffmpeg", "fonts"),
    "broll": ("pexels",),
    "candidates": ("fal",),
    "build": ("ffmpeg", "fonts"),
    "grade": ("ffmpeg",),
    "verify": ("ffmpeg",),
}

_CAPABILITY_FIX = {
    "ffmpeg": "install ffmpeg (`brew install ffmpeg`)",
    "fonts": "run `quinn-video fonts`",
    "heygen": "set HEYGEN_API_KEY in .env",
    "pexels": "set PEXELS_API_KEY in .env",
    "fal": "set FAL_KEY in .env",
}


class NotReadyError(RuntimeError):
    """A stage was asked to run without what it needs."""


def _capability_checks(capability: str, keys: Keys) -> list[Check]:
    if capability == "ffmpeg":
        return [c for c in check_ffmpeg() if c.fatal]
    if capability == "fonts":
        return list(check_fonts())
    if capability == "heygen":
        return [Check("HEYGEN_API_KEY", bool(keys.heygen), "missing")]
    if capability == "pexels":
        return [Check("PEXELS_API_KEY", bool(keys.pexels), "missing")]
    if capability == "fal":
        return [Check("FAL_KEY", bool(keys.fal), "missing")]
    return []


def preflight(command: str, *, bypass: bool = False) -> None:
    """Refuse to start a stage that cannot finish.

    Without this a missing key surfaces as a ConfigError several stages in,
    and a missing codec as an ffmpeg failure inside a filter graph -- after
    the expensive calls have already been made. These checks are local and
    take milliseconds, so there is no reason not to run them every time.
    """
    if bypass or os.environ.get("QUINN_SKIP_PREFLIGHT"):
        return

    needs = NEEDS.get(command, ())
    if not needs:
        return

    keys = Keys.load()
    failed: list[tuple[str, Check]] = [
        (capability, check)
        for capability in needs
        for check in _capability_checks(capability, keys)
        if not check.ok
    ]
    if not failed:
        return

    if command == "init":
        lines = ["Nothing in this pipeline can run yet:"]
    else:
        lines = [f"`{command}` cannot run yet:"]
    lines += [
        f"  {FAIL} {check.name:<20} {_CAPABILITY_FIX.get(capability, check.detail)}"
        for capability, check in failed
    ]
    lines.append("\nRun `quinn-video doctor` for the full picture.")
    if command == "init":
        lines.append(
            "Fix these before writing a script — a storyboard you cannot render "
            "is wasted work.\nTo draft one anyway, pass --draft."
        )
    raise NotReadyError("\n".join(lines))


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


# HeyGen labels gender inconsistently across catalogue vintages -- "female"
# and "Woman" both occur, as do "male" and "Man" -- so a filter that matches
# the field literally silently drops half the pool.
_GENDER = {
    "female": "female",
    "woman": "female",
    "f": "female",
    "male": "male",
    "man": "male",
    "m": "male",
}


def normalise_gender(value: str | None) -> str | None:
    return _GENDER.get((value or "").strip().lower())


def presenters(
    *,
    gender: str | None = None,
    search: str | None = None,
    limit: int = 24,
    sheet: bool = False,
    use: str | None = None,
) -> int:
    """Choose the presenter, without reading the source to find out how.

    Picking a face is a taste decision and the catalogue is ten thousand
    entries deep, so this filters it to something viewable, renders the
    previews as one sheet that can actually be looked at, and writes the
    choice where the pipeline will find it.
    """
    if use:
        return _use_presenter(use)

    mine, pool = _avatar_catalogue()
    own_ids = {m.get("id") for m in mine}
    want = normalise_gender(gender)
    if gender and not want:
        print(f'unknown gender "{gender}" — use female or male')
        return 2

    def usable(a: dict) -> bool:
        if a.get("status") not in (None, "completed"):
            return False
        if want and normalise_gender(a.get("gender")) != want:
            return False
        return not (search and search.lower() not in (a.get("name") or "").lower())

    def rank(a: dict) -> tuple:
        engines = a.get("supported_api_engines") or []
        return (
            0 if a.get("id") in own_ids else 1,
            0 if a.get("preferred_orientation") == "portrait" else 1,
            0 if "avatar_v" in engines else 1 if "avatar_iv" in engines else 2,
            (a.get("name") or "").lower(),
        )

    # One person appears as dozens of looks -- eight angles of the same face
    # is not a choice. Keep the best-ranked look per group so the list is
    # distinct people.
    best: dict[str, dict] = {}
    for avatar in sorted((a for a in pool if usable(a)), key=rank):
        key = avatar.get("group_id") or avatar.get("name") or avatar.get("id") or ""
        best.setdefault(str(key), avatar)
    shortlist = list(best.values())[:limit]
    if not shortlist:
        print("nothing matched. Try dropping --gender or --search.")
        return 1

    label = f"{len(shortlist)} shown"
    if want:
        label += f", {want}"
    print(f"\n{label} ({len(mine)} on your account)\n")
    print(f"  {'':2} {'#':<4}{'id':<36} {'name':<24} {'sex':<7} {'orient':<9} engines")
    print(f"  {'':2} {'-' * 3:<4}{'-' * 36} {'-' * 24} {'-' * 7} {'-' * 9} {'-' * 14}")
    for index, avatar in enumerate(shortlist, 1):
        engines = ",".join(
            e.replace("avatar_", "") for e in avatar.get("supported_api_engines") or []
        )
        print(
            f"  {'*' if avatar.get('id') in own_ids else ' ':2} {index:<4}"
            f"{(avatar.get('id') or '')[:36]:<36} {(avatar.get('name') or '')[:24]:<24} "
            f"{(normalise_gender(avatar.get('gender')) or '-'):<7} "
            f"{(avatar.get('preferred_orientation') or '-'):<9} {engines}"
        )

    if sheet:
        path = _presenter_sheet(shortlist)
        print(f"\n  sheet: {path}")
        print("  Look at it before choosing — the names carry no information.")

    print("\n  * = on your account. Portrait looks first: natively 1080x1920,")
    print("  so nothing is cropped at 9:16.")
    print("  Choose with:  quinn-video presenters --use <id>\n")
    return 0


def _presenter_sheet(avatars: list[dict]) -> Path:
    """Render the previews as one numbered sheet, matching the b-roll sheets."""
    import math

    import httpx
    from PIL import Image, ImageDraw

    from . import fonts
    from .config import CACHE

    cols, cw, ch, caption = 6, 240, 320, 30
    rows = math.ceil(len(avatars) / cols)
    sheet = Image.new("RGB", (cols * cw, rows * (ch + caption)), (18, 20, 24))
    draw = ImageDraw.Draw(sheet)
    label = fonts.load(fonts.CAPTION, 18)

    thumbs = CACHE / "avatar-previews"
    thumbs.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for index, avatar in enumerate(avatars):
            x, y = (index % cols) * cw, (index // cols) * (ch + caption)
            url = avatar.get("preview_image_url")
            cached = thumbs / f"{avatar.get('id')}.jpg"
            try:
                if not cached.exists() and url:
                    cached.write_bytes(client.get(url).content)
                with Image.open(cached) as raw:
                    thumb = raw.convert("RGB")
                    scale = max(cw / thumb.width, ch / thumb.height)
                    thumb = thumb.resize((round(thumb.width * scale), round(thumb.height * scale)))
                    sheet.paste(thumb.crop((0, 0, cw, ch)), (x, y))
            except Exception:
                draw.text((x + 8, y + 8), "no preview", font=label, fill=(200, 80, 80))
            draw.text(
                (x + 6, y + ch + 6),
                f"{index + 1}. {(avatar.get('name') or '')[:26]}",
                font=label,
                fill=(235, 235, 240),
            )

    dest = CACHE / "presenters.jpg"
    sheet.save(dest, quality=85)
    return dest


def _use_presenter(avatar_id: str) -> int:
    """Write the choice to the workspace .env, where every stage reads it."""
    from .config import WORKSPACE
    from .heygen import HeyGen

    with HeyGen() as client:
        avatar = client.avatar(avatar_id)
    if not avatar:
        print(f"no avatar {avatar_id} on this account or in the public library")
        return 2

    env = WORKSPACE / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    kept = [ln for ln in lines if not ln.startswith("QUINN_AVATAR_ID=")]
    kept.append(f"QUINN_AVATAR_ID={avatar_id}")
    env.write_text("\n".join(kept).strip() + "\n", encoding="utf-8")

    print(f"presenter: {avatar.get('name')} ({normalise_gender(avatar.get('gender')) or '?'})")
    print(f"  written to {env}")
    voice = avatar.get("default_voice_id")
    if voice:
        print(f"  its default voice is {voice}; `quinn-video audition` ranks the alternatives.")
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
