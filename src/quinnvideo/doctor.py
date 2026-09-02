"""Preflight checks.

Runs before anything that costs money. Every paid call in this pipeline is
preceded by something that can fail for free -- a missing key, an ffmpeg
without the right codec, an absent font -- and finding those out three
minutes into an avatar render is a bad trade.
"""

from __future__ import annotations

import io
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


_GENDER = {
    "female": "female",
    "woman": "female",
    "male": "male",
    "man": "male",
}


def normalise_gender(value: str | None) -> str | None:
    """HeyGen labels gender inconsistently across catalogue vintages."""
    return _GENDER.get((value or "").strip().lower())


HEYGEN_LIBRARY = "https://app.heygen.com/avatars"


def presenters(target: str | None = None, *, use: str | None = None) -> int:
    """Choose the presenter from a HeyGen URL.

    There is no browser here, and building one was the wrong instinct. HeyGen's
    own library has video previews, search and filters that no contact sheet
    rendered into a terminal can match, and the avatar id sits in the URL. So
    the user browses there and pastes a link.

    What is left for this to do is the part their UI does not: a library URL
    names a *person* -- one group, whose looks differ by room and outfit --
    while a render needs one specific look. Maeve is twenty-five of them, with
    names like "Therapy Coach 2" that distinguish nothing. That narrowing is
    what the sheet is for.
    """
    if use:
        return _use_presenter(use)
    if not target:
        print(f"\n  Browse the library:  {HEYGEN_LIBRARY}")
        print("  Then paste the URL:  quinn-video presenters <url>\n")
        return 0

    ident, problem = _group_of(target)
    if problem:
        print(problem)
        return 2

    looks = _looks_in(ident or "")
    if not looks:
        print(f"no looks found for {ident}")
        return 2

    if len(looks) == 1:
        # A custom avatar is its own group. Nothing to choose, so choose it.
        return _use_presenter(looks[0]["id"])

    looks.sort(key=lambda a: (a.get("preferred_orientation") != "portrait", a.get("name") or ""))
    _remember(looks)
    person = (looks[0].get("name") or "").split()[0]
    sheet = _presenter_sheet(looks[:24], f"looks-{person.lower()}")

    print(f"\n{person} has {len(looks)} looks — they differ by room and outfit,")
    print("and a render needs one.\n")
    for index, look in enumerate(looks[:24], 1):
        print(
            f"  {index:<4}{(look.get('name') or '')[:46]:<48}"
            f"{look.get('preferred_orientation') or '-'}"
        )
    print(f"\n  sheet: {sheet}")
    print("  quinn-video presenters --use <number>\n")
    return 0


def _looks_in(group_id: str) -> list[dict]:
    """Every look belonging to one person.

    Filtering the listing by group is what removed the catalogue scan: the
    whole library is ten thousand looks and walking it took two minutes, to
    answer a question the API answers directly.
    """
    from .heygen import HeyGen

    with HeyGen() as client:
        looks = list(client.avatars_in_group(group_id))
    return [a for a in looks if a.get("status") in (None, "completed")]


def _group_of(target: str) -> tuple[str | None, str]:
    """The group id behind a URL, a look id, or a group id."""
    import re

    from .heygen import HeyGen

    text = target.strip()
    if "heygen.com" in text.lower() or text.startswith("http"):
        found = re.findall(r"[0-9a-f]{32}", text.lower())
        if not found:
            return None, f"no avatar id in that URL: {text[:80]}"
        text = found[0]

    if not re.fullmatch(r"[0-9a-f]{32}", text.lower()):
        return None, f'"{text[:60]}" is not a HeyGen URL or avatar id'

    ident = text.lower()
    # A library URL carries the group; a look id resolves directly. Try the
    # look first, since that also tells us its group for free.
    with HeyGen() as client:
        look = client.avatar(ident)
    return (look.get("group_id") or ident) if look else ident, ""


def _presenter_sheet(avatars: list[dict], slug: str = "") -> Path:
    """Render the previews as one numbered sheet.

    Cells are landscape-shaped and the whole frame is fitted inside them
    rather than cropped to fill. Cropping was wrong twice over: five of every
    six avatars in the library are landscape, and taking a portrait-shaped
    bite out of one showed a slice of empty room with the subject outside the
    frame entirely. A sheet whose job is "who is this" must show the subject.
    """
    import math

    import httpx
    from PIL import Image, ImageDraw

    from . import fonts
    from .config import CACHE

    cols, cw, ch, caption = 4, 360, 240, 26
    rows = math.ceil(len(avatars) / cols)
    sheet = Image.new("RGB", (cols * cw, rows * (ch + caption)), (18, 20, 24))
    draw = ImageDraw.Draw(sheet)
    label = fonts.load(fonts.CAPTION, 17)

    thumbs = CACHE / "avatar-previews"
    thumbs.mkdir(parents=True, exist_ok=True)

    def fit(raw: Image.Image) -> Image.Image:
        """Whole image inside the cell, centred, letterboxed."""
        scale = min(cw / raw.width, ch / raw.height)
        small = raw.resize((max(1, round(raw.width * scale)), max(1, round(raw.height * scale))))
        cell = Image.new("RGB", (cw, ch), (18, 20, 24))
        cell.paste(small, ((cw - small.width) // 2, (ch - small.height) // 2))
        return cell

    def shorten(text: str) -> str:
        """Trim to the cell, measured rather than guessed at a character count.

        The names repeat the person in every look -- "Maeve Therapy Coach 2" --
        so a fixed truncation runs past the cell and overwrites its neighbour.
        """
        if draw.textlength(text, font=label) <= cw - 14:
            return text
        while text and draw.textlength(text + "…", font=label) > cw - 14:
            text = text[:-1]
        return text.rstrip() + "…"

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for index, avatar in enumerate(avatars):
            x, y = (index % cols) * cw, (index // cols) * (ch + caption)
            url = avatar.get("preview_image_url")
            cached = thumbs / f"{avatar.get('id')}.jpg"
            try:
                if not cached.exists() and url:
                    # Stored at sheet size, not the 1.4 MB original: the whole
                    # catalogue at full resolution is two gigabytes.
                    with Image.open(io.BytesIO(client.get(url).content)) as raw:
                        fit(raw.convert("RGB")).save(cached, quality=88)
                with Image.open(cached) as raw:
                    sheet.paste(raw.convert("RGB"), (x, y))
            except Exception:
                draw.text((x + 8, y + 8), "no preview", font=label, fill=(200, 80, 80))
            draw.rectangle([x, y + ch, x + cw - 1, y + ch + caption - 1], fill=(24, 26, 31))
            draw.text(
                (x + 7, y + ch + 5),
                shorten(f"{index + 1}. {avatar.get('name') or ''}"),
                font=label,
                fill=(235, 235, 240),
            )

    # Named for the filter that produced it: browsing female then male looks
    # otherwise overwrites the first sheet with the second.
    dest = CACHE / f"presenters{'-' + slug if slug else ''}.jpg"
    sheet.save(dest, quality=88)
    return dest


def _manifest_path() -> Path:
    from .config import CACHE

    return CACHE / "presenters-last.json"


def _remember(shortlist: list[dict]) -> None:
    import json

    _manifest_path().parent.mkdir(parents=True, exist_ok=True)
    _manifest_path().write_text(
        json.dumps(
            [
                {
                    "n": i,
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "gender": normalise_gender(a.get("gender")),
                    "preview": a.get("preview_image_url"),
                }
                for i, a in enumerate(shortlist, 1)
            ],
            indent=2,
        ),
        encoding="utf-8",
    )


def _resolve(choice: str) -> tuple[str | None, str]:
    """Turn a number, a name, an id or a URL into one look id.

    The number is the important one. Nobody reads a 32-character hex string
    off a contact sheet; the number beside the face is what a person says.
    """
    import json
    import re

    text = choice.strip()
    if "heygen.com" in text.lower() or text.startswith("http"):
        found = re.findall(r"[0-9a-f]{32}", text.lower())
        if not found:
            return None, f"no avatar id in that URL: {text[:80]}"
        return found[0], ""
    if re.fullmatch(r"[0-9a-f]{32}", text.lower()):
        return text.lower(), ""

    path = _manifest_path()
    if not path.exists():
        return None, "paste a HeyGen URL first — there is no list to pick from yet"
    entries = json.loads(path.read_text(encoding="utf-8"))

    if text.isdigit():
        match = next((e for e in entries if e["n"] == int(text)), None)
        if not match:
            return None, f"there is no {text} in the last list ({len(entries)} shown)"
        return match["id"], ""

    named = [e for e in entries if (e["name"] or "").lower().startswith(text.lower())]
    if not named:
        return None, f'nothing in the last list is called "{text}"'
    if len({e["id"] for e in named}) > 1:
        which = ", ".join(f"{e['n']}. {e['name']}" for e in named[:6])
        return None, f'"{text}" matches several — pick a number: {which}'
    return named[0]["id"], ""


def _use_presenter(choice: str) -> int:
    """Set the presenter from a number, a name, or an id."""
    from .config import WORKSPACE
    from .heygen import HeyGen

    avatar_id, problem = _resolve(choice)
    if problem:
        print(problem)
        return 2

    with HeyGen() as client:
        avatar = client.avatar(avatar_id or "")
    if not avatar:
        print(f"no avatar {avatar_id} on this account or in the public library")
        return 2

    env = WORKSPACE / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    kept = [ln for ln in lines if not ln.startswith("QUINN_AVATAR_ID=")]
    kept.append(f"QUINN_AVATAR_ID={avatar_id}")
    env.write_text("\n".join(kept).strip() + "\n", encoding="utf-8")

    name = avatar.get("name") or avatar_id
    print(f"\npresenter: {name} ({normalise_gender(avatar.get('gender')) or '?'})")

    # Show who was actually chosen. A name in a terminal is not confirmation
    # when eight avatars share one, and the whole point of picking a face is
    # that it was seen.
    portrait = _save_preview(avatar)
    if portrait:
        print(f"  {portrait}")
    print(f"  saved to {env}")

    voice = avatar.get("default_voice_id")
    if voice:
        print(f"  its default voice is {voice}; `quinn-video audition` ranks alternatives.\n")
    return 0


def _save_preview(avatar: dict) -> Path | None:
    """Keep the chosen presenter's preview where it can be looked at."""
    import httpx

    from .config import CACHE

    url = avatar.get("preview_image_url")
    if not url:
        return None
    dest = CACHE / "presenter-chosen.jpg"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            dest.write_bytes(client.get(url).content)
    except Exception:
        return None
    return dest


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
