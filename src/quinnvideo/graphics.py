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
from .config import HEIGHT, WIDTH

# High-visibility yellow. Borrowed from the safety vests the footage is full
# of, which makes the accent feel native to the subject rather than applied.
HI_VIS = (255, 214, 0, 255)
WHITE = (255, 255, 255, 255)
INK = (10, 10, 12, 255)


@dataclass
class CaptionStyle:
    size: int = 78

    # These are *optical* gaps: the space you actually see between one
    # stroked word and the next. The stroke grows each word outward on every
    # side, so the advance the layout needs is this plus twice the stroke.
    # Treating them as raw advances is how the first version ended up with
    # 20px of nominal spacing and 2px of visible gap, which read as one word.
    # 16 reads as a natural word space for a face this heavy. Tighter starts
    # to merge once the active word takes its scale pop; looser reads as airy
    # and slows the phrase down.
    word_gap: int = 16
    line_gap: int = 22

    stroke: int = 9
    shadow_offset: tuple[int, int] = (0, 6)
    shadow_alpha: int = 150
    max_width: int = WIDTH - 150

    # High enough to clear the cornered presenter, low enough to stay out of
    # the way of whatever the footage is actually showing.
    baseline_y: int = HEIGHT - 800

    spoken: tuple[int, int, int, int] = WHITE
    active: tuple[int, int, int, int] = HI_VIS

    pop_scale: float = 1.14
    pop_duration: float = 0.13

    @property
    def advance(self) -> int:
        """Horizontal distance between word origins."""
        return self.word_gap + 2 * self.stroke

    @property
    def line_height(self) -> int:
        """Vertical distance between line baselines."""
        return self.size + self.line_gap + 2 * self.stroke

    # How a phrase builds. "in-place" lays the whole phrase out once and
    # reveals words at their final positions, so the line grows left to
    # right. "recenter" re-centres the visible words on every beat, which
    # keeps a short line optically centred but drags the words already on
    # screen leftwards -- and the eye reads that drift as the text arriving
    # right to left, which is the wrong way round for English.
    reveal: str = "in-place"


@dataclass
class Token:
    """One word, positioned within its group."""

    text: str
    start: float
    end: float
    width: float = 0.0
    # Authored in the storyboard. An emphasised word keeps the accent colour
    # after it has been spoken, instead of reverting to white with the rest
    # of the phrase.
    emphasised: bool = False


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
        """Work out where each word sits for every stage of the reveal."""
        for token in group.tokens:
            token.width = self.measure(token.text)

        if self.style.reveal == "in-place":
            # One layout for the finished phrase; each prefix is simply the
            # front of it. Words therefore appear where they will stay, and
            # the line builds left to right the way it is read.
            positions = self._layout_prefix(group.tokens)
            for count in range(1, len(group.tokens) + 1):
                group.layouts[count] = positions[:count]
            return

        for count in range(1, len(group.tokens) + 1):
            group.layouts[count] = self._layout_prefix(group.tokens[:count])

    def _layout_prefix(self, tokens: list[Token]) -> list[tuple[float, float]]:
        style = self.style
        lines: list[list[Token]] = [[]]
        widths: list[float] = [0.0]

        for token in tokens:
            addition = token.width + (style.advance if lines[-1] else 0)
            if lines[-1] and widths[-1] + addition > style.max_width:
                lines.append([token])
                widths.append(token.width)
            else:
                lines[-1].append(token)
                widths[-1] += addition

        # Grow upward from the baseline so a second line never pushes the
        # phrase down into the platform UI.
        top = style.baseline_y - (len(lines) - 1) * style.line_height

        positions: list[tuple[float, float]] = []
        for row, (line, width) in enumerate(zip(lines, widths, strict=True)):
            x = (WIDTH - width) / 2
            y = top + row * style.line_height
            for token in line:
                positions.append((x, y))
                x += token.width + style.advance
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
            colour = style.active if (is_active or token.emphasised) else style.spoken

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


# --- beat overlays -------------------------------------------------------


def draw_overlay(canvas, text: str, progress: float, *, kind: str = "stat") -> None:
    """Draw a beat's stat or label into the overlay layer.

    Sits in the upper third, well clear of the caption line and the cornered
    presenter, and uses the same stroke-and-shadow treatment as the captions
    so the two read as one system rather than two.
    """
    from PIL import ImageDraw

    if progress <= 0.01:
        return

    draw = ImageDraw.Draw(canvas)
    face = fonts.load(fonts.DISPLAY, 78 if kind == "stat" else 60)
    alpha = round(255 * min(1.0, progress))
    # Slides up as it fades in; a graphic that simply appears reads as a bug.
    lift = round(26 * (1.0 - _ease_out(min(1.0, progress))))

    x, y = 96, 300 + lift
    draw.rectangle([x, y - 34, x + 132, y - 22], fill=(*HI_VIS[:3], alpha))

    for line in _wrap(face, text.upper(), WIDTH - 320):
        draw.text(
            (x + 4, y + 6),
            line,
            font=face,
            fill=(0, 0, 0, round(alpha * 0.55)),
            stroke_width=8,
            stroke_fill=(0, 0, 0, round(alpha * 0.55)),
        )
        draw.text(
            (x, y),
            line,
            font=face,
            fill=(255, 255, 255, alpha),
            stroke_width=8,
            stroke_fill=(*INK[:3], alpha),
        )
        y += 92


# --- fallback graphics ---------------------------------------------------


def render_card(text: str, dest, *, kicker: str = "", accent=HI_VIS):
    # NOTE: `kicker` is shown to the viewer. Never pass internal plumbing --
    # a search query or a visual intent -- into it.
    """A designed full-frame card, used when no honest footage exists.

    This is the last rung of the b-roll fallback ladder. The brief forbids
    anything off-topic, so when stock libraries have nothing that genuinely
    shows the thing being described, the right answer is a deliberate
    typographic frame -- not a loosely related shot of somebody in a hard hat.
    A card reads as an editorial choice; a wrong clip reads as a mistake.
    """
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (WIDTH, HEIGHT), (18, 20, 24))
    draw = ImageDraw.Draw(canvas)

    # Vertical wash so the frame is not a flat rectangle behind the captions.
    for y in range(HEIGHT):
        shade = 18 + int(26 * (y / HEIGHT))
        draw.line([(0, y), (WIDTH, y)], fill=(shade, shade + 2, shade + 6))

    display = fonts.load(fonts.DISPLAY, 132)
    label = fonts.load(fonts.CAPTION, 40)

    # Text sits in the upper half; captions own the lower third.
    y = 470
    if kicker:
        draw.text((110, y - 90), kicker.upper(), font=label, fill=accent[:3])

    for line in _wrap(display, text.upper(), WIDTH - 220):
        draw.text((110, y), line, font=display, fill=(245, 245, 248))
        y += 150

    draw.rectangle([110, y + 30, 110 + 180, y + 44], fill=accent[:3])

    canvas.save(dest, quality=95)
    return dest


def _wrap(font, text: str, limit: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if font.getlength(trial) > limit and line:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines
