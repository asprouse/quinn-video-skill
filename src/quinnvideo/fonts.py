"""Caption typeface management.

Fonts are downloaded on setup rather than committed, which keeps the repo
free of binary blobs and keeps each face under its own upstream licence.
Both faces below are SIL Open Font License 1.1, so bundling the *output*
of this pipeline commercially is unencumbered.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import FONTS

RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl"


@dataclass(frozen=True)
class Face:
    filename: str
    url: str
    role: str
    variation: str | None = None

    @property
    def path(self) -> Path:
        return FONTS / self.filename


# Montserrat carries the captions: geometric, wide apertures, and legible at
# speed against busy footage. Anton handles big numbers and stat cards, where
# the condensed width buys us more glyphs per line without shrinking them.
CAPTION = Face(
    filename="Montserrat.ttf",
    url=f"{RAW}/montserrat/Montserrat%5Bwght%5D.ttf",
    role="captions and lower thirds",
    variation="ExtraBold",
)
DISPLAY = Face(
    filename="Anton-Regular.ttf",
    url=f"{RAW}/anton/Anton-Regular.ttf",
    role="stat cards and numerals",
)

FACES = (CAPTION, DISPLAY)


def install(force: bool = False) -> int:
    FONTS.mkdir(parents=True, exist_ok=True)

    for face in FACES:
        if face.path.exists() and not force:
            print(f"  ✓ {face.filename} already present")
            continue
        print(f"  → downloading {face.filename} ({face.role})")
        response = httpx.get(face.url, follow_redirects=True, timeout=60.0)
        response.raise_for_status()
        face.path.write_bytes(response.content)
        print(f"  ✓ {face.filename} ({len(response.content) // 1024} KB)")

    (FONTS / "LICENSE.md").write_text(
        "Montserrat and Anton are licensed under the SIL Open Font License 1.1.\n"
        "https://openfontlicense.org/\n"
        "Downloaded from https://github.com/google/fonts\n",
        encoding="utf-8",
    )
    return 0


def load(face: Face, size: int):
    """Open a face at a pixel size, applying its named weight if it is variable."""
    from PIL import ImageFont

    if not face.path.exists():
        raise FileNotFoundError(
            f"{face.path} is missing. Run `quinn-video fonts` to download typefaces."
        )

    font = ImageFont.truetype(str(face.path), size)
    if face.variation:
        # A static build of the same family, or a FreeType without variation
        # support, leaves the default instance -- which is still usable.
        with suppress(OSError):
            font.set_variation_by_name(face.variation)
    return font
