"""The visual language: captions and overlay graphics, drawn with Pillow.

Everything here renders onto a transparent RGBA canvas that is later
composited over the b-roll. Doing our own text rendering (rather than handing
an .ass file to libass) buys three things: it works on any ffmpeg build, it
gives us per-word animation that subtitle formats make awkward, and the same
code draws the stat cards and the fallback graphics.

Legibility over unpredictable footage is the whole problem. Every piece of
text gets a heavy stroke and a shadow, because we cannot know whether the
frame behind it is a white hard hat or a black tyre.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

from . import fonts
from .config import HEIGHT, SAFE_BOTTOM, WIDTH

# High-visibility yellow. Borrowed from the safety vests the footage is full
# of, which makes the accent feel native to the subject rather than applied.
HI_VIS = (255, 214, 0, 255)
WHITE = (255, 255, 255, 255)
INK = (10, 10, 12, 255)


@dataclass
class CaptionStyle:
    size: int = 78
    line_gap: int = 22
    word_gap: int = 20
    stroke: int = 9
    shadow_offset: tuple[int, int] = (0, 6)
    shadow_alpha: int = 150
    max_width: int = WIDTH - 150

    # Captions sit above the platform UI but below the middle of the frame,
    # where they overlap the least interesting part of most footage.
    baseline_y: int = HEIGHT - SAFE_BOTTOM - 210

    spoken: tuple[int, int, int, int] = WHITE
    active: tuple[int, int, int, int] = HI_VIS

    pop_scale: float = 1.14
    pop_duration: float = 0.13


@dataclass
class Token:
    """One word, positioned within its group."""

    text: str
    start: float
    end: float
    width: float = 0.0


@dataclass
class Group:
    """A phrase shown as a unit. Words within it appear one at a time."""

    tokens: list[Token] = field(default_factory=list)
    # Positions are stored per prefix length: showing two words of a phrase is
    # a different layout from showing four, because the visible words stay
    # centred as the line grows.
    layouts: dict[int, list[tuple[float, float]]] = field(default_factory=dict)

    @property
    def start(self) -> float:
        return self.tokens[0].start

    @property
    def end(self) -> float:
        return self.tokens[-1].end

    def active_index(self, t: float) -> int:
        """Index of the word being spoken at time ``t``.

        Words hold their highlight through the gap that follows them, so the
        accent never blinks off between words in a phrase.
        """
        for i, token in enumerate(self.tokens):
            if t < token.end:
                return i
        return len(self.tokens) - 1


class Renderer:
    def __init__(self, style: CaptionStyle | None = None) -> None:
        self.style = style or CaptionStyle()
        self.font = fonts.load(fonts.CAPTION, self.style.size)
        self._pop_cache: dict[int, ImageFont.FreeTypeFont] = {}

    # --- measurement -----------------------------------------------------

    def measure(self, text: str, font: ImageFont.FreeTypeFont | None = None) -> float:
        font = font or self.font
        return font.getlength(text)

    def _scaled_font(self, scale: float) -> ImageFont.FreeTypeFont:
        size = max(1, round(self.style.size * scale))
        if size not in self._pop_cache:
            self._pop_cache[size] = fonts.load(fonts.CAPTION, size)
        return self._pop_cache[size]

    # --- layout ----------------------------------------------------------

    def layout(self, group: Group) -> None:
        """Compute a centred layout for every prefix of the phrase.

        Words appear one at a time, so the line is a different width on every
        beat. Re-centring each time keeps the phrase optically anchored to the
        middle of the frame instead of drifting in from the left, which is
        what happens if you reserve space for words nobody has said yet.
        """
        for token in group.tokens:
            token.width = self.measure(token.text)
        for count in range(1, len(group.tokens) + 1):
            group.layouts[count] = self._layout_prefix(group.tokens[:count])

    def _layout_prefix(self, tokens: list[Token]) -> list[tuple[float, float]]:
        style = self.style
        lines: list[list[Token]] = [[]]
        widths: list[float] = [0.0]

        for token in tokens:
            addition = token.width + (style.word_gap if lines[-1] else 0)
            if lines[-1] and widths[-1] + addition > style.max_width:
                lines.append([token])
                widths.append(token.width)
            else:
                lines[-1].append(token)
                widths[-1] += addition

        line_height = style.size + style.line_gap
        # Grow upward from the baseline so a second line never pushes the
        # phrase down into the platform UI.
        top = style.baseline_y - (len(lines) - 1) * line_height

        positions: list[tuple[float, float]] = []
        for row, (line, width) in enumerate(zip(lines, widths)):
            x = (WIDTH - width) / 2
            y = top + row * line_height
            for token in line:
                positions.append((x, y))
                x += token.width + style.word_gap
        return positions

    # --- drawing ---------------------------------------------------------

    def draw_group(self, canvas: Image.Image, group: Group, t: float) -> None:
        style = self.style
        active = group.active_index(t)
        # Only words already spoken are on screen, so the visible line is the
        # prefix ending at the active word.
        visible = active + 1
        positions = group.layouts.get(visible)
        if not positions:
            return

        draw = ImageDraw.Draw(canvas)

        for i, token in enumerate(group.tokens[:visible]):
            is_active = i == active
            colour = style.active if is_active else style.spoken

            font = self.font
            x, y = positions[i]

            if is_active:
                # A short scale pop on the leading word. It is drawn about the
                # word's own centre so the rest of the line stays put; the
                # slight overlap with neighbours lasts ~4 frames and reads as
                # emphasis rather than collision.
                progress = min(1.0, max(0.0, (t - token.start) / style.pop_duration))
                scale = style.pop_scale - (style.pop_scale - 1.0) * _ease_out(progress)
                if scale > 1.001:
                    font = self._scaled_font(scale)
                    grown = self.measure(token.text, font)
                    x -= (grown - token.width) / 2
                    y -= (style.size * (scale - 1.0)) / 2

            self._text(draw, (x, y), token.text, colour, font)

    def _text(
        self,
        draw: ImageDraw.ImageDraw,
        xy: tuple[float, float],
        text: str,
        colour: tuple[int, int, int, int],
        font: ImageFont.FreeTypeFont,
    ) -> None:
        style = self.style
        x, y = xy
        dx, dy = style.shadow_offset

        # Shadow first, then stroked fill. The stroke handles contrast against
        # busy footage; the shadow separates the text from flat backgrounds
        # where a stroke alone still reads as pasted on.
        draw.text(
            (x + dx, y + dy),
            text,
            font=font,
            fill=(0, 0, 0, style.shadow_alpha),
            stroke_width=style.stroke,
            stroke_fill=(0, 0, 0, style.shadow_alpha),
        )
        draw.text(
            (x, y),
            text,
            font=font,
            fill=colour,
            stroke_width=style.stroke,
            stroke_fill=INK,
        )


def _ease_out(t: float) -> float:
    """Cubic ease-out. Fast attack, soft settle -- reads as a snap, not a slide."""
    return 1.0 - (1.0 - t) ** 3


def blank() -> Image.Image:
    return Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
