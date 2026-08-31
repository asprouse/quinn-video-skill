"""Generated motion graphics.

Some ideas are geometric, and no stock library has footage of them. The 4:1
ladder rule is the clearest case: it is a statement about an angle, so the
honest way to show it is to draw the angle. These clips join the b-roll track
as ordinary shots, so the cut list schedules them like any other footage.

Drawn at 2x and downsampled -- Pillow's lines have no antialiasing, and the
whole point of the shot is a clean diagonal.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from . import fonts
from .config import FPS, HEIGHT, WIDTH
from .graphics import HI_VIS

SS = 2  # supersample factor

INK = (243, 244, 247)
DIM = (138, 146, 158)
GROUND = (92, 99, 110)
BG_TOP = (16, 18, 22)
BG_BOTTOM = (26, 29, 35)


def _ease(t: float) -> float:
    """Cubic ease-out, clamped."""
    t = min(1.0, max(0.0, t))
    return 1.0 - (1.0 - t) ** 3


def _phase(t: float, start: float, length: float) -> float:
    return _ease((t - start) / length) if length > 0 else 1.0


def _ladder(
    draw: ImageDraw.ImageDraw,
    base: tuple[float, float],
    top: tuple[float, float],
    *,
    width: float,
    colour: tuple[int, int, int],
    rail: int,
    rung_gap: float,
) -> None:
    """Draw a two-rail ladder with rungs between two points."""
    bx, by = base
    tx, ty = top
    length = math.hypot(tx - bx, ty - by)
    if length < 1:
        return
    dx, dy = (tx - bx) / length, (ty - by) / length
    px, py = -dy * width / 2, dx * width / 2

    for sign in (1, -1):
        draw.line(
            [(bx + px * sign, by + py * sign), (tx + px * sign, ty + py * sign)],
            fill=colour,
            width=rail,
        )

    steps = max(2, int(length / rung_gap))
    for i in range(1, steps):
        cx, cy = bx + dx * length * i / steps, by + dy * length * i / steps
        draw.line(
            [(cx + px, cy + py), (cx - px, cy - py)], fill=colour, width=max(2, rail - 2)
        )


def _dimension(
    draw: ImageDraw.ImageDraw,
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    progress: float,
    colour: tuple[int, int, int],
    tick: int = 26,
) -> None:
    """A dimension line with end ticks, drawn in over ``progress``."""
    ax, ay = a
    bx, by = b
    cx, cy = ax + (bx - ax) * progress, ay + (by - ay) * progress
    draw.line([(ax, ay), (cx, cy)], fill=colour, width=5)

    vertical = abs(by - ay) > abs(bx - ax)
    for (x, y), shown in (((ax, ay), True), ((bx, by), progress > 0.98)):
        if not shown:
            continue
        if vertical:
            draw.line([(x - tick, y), (x + tick, y)], fill=colour, width=5)
        else:
            draw.line([(x, y - tick), (x, y + tick)], fill=colour, width=5)


def _hatch(draw, x0, y0, x1, y1, *, spacing, length, colour, vertical=False):
    """Engineering-drawing hatching, for the solid side of a surface."""
    if vertical:
        y = y0
        while y < y1:
            draw.line([(x0, y), (x0 - length, y + length)], fill=colour, width=3)
            y += spacing
    else:
        x = x0
        while x < x1:
            draw.line([(x, y0), (x - length, y0 + length)], fill=colour, width=3)
            x += spacing


def _arrow(draw, tip, direction, *, size, colour):
    """A small solid arrowhead at ``tip`` pointing along ``direction``."""
    dx, dy = direction
    px, py = -dy, dx
    draw.polygon(
        [
            tip,
            (tip[0] - dx * size + px * size * 0.45, tip[1] - dy * size + py * size * 0.45),
            (tip[0] - dx * size - px * size * 0.45, tip[1] - dy * size - py * size * 0.45),
        ],
        fill=colour,
    )


def render_ladder_angle(
    dest: Path,
    duration: float,
    *,
    fps: int = FPS,
    ratio: tuple[int, int] = (4, 1),
    cues: dict[str, float] | None = None,
) -> Path:
    """Animate the 4-to-1 rule: a ladder swinging out to its correct angle.

    ``cues`` maps phase names -- structure, ladder, rise, run -- to seconds
    from the start of the shot. Pass the times of the words that name them and
    the drawing lands on the narration instead of running to its own clock,
    which is the difference between a diagram and a decoration.
    """
    from .ff import VideoWriter

    up, out = ratio
    cues = cues or {}
    at_structure = cues.get("structure", 0.15)
    at_ladder = cues.get("ladder", 0.55)
    at_rise = cues.get("rise", 1.25)
    at_run = cues.get("run", 1.70)

    title = fonts.load(fonts.DISPLAY, 128 * SS)
    label = fonts.load(fonts.DISPLAY, 72 * SS)
    kicker = fonts.load(fonts.CAPTION, 33 * SS)
    small = fonts.load(fonts.CAPTION, 30 * SS)

    # Everything sits above y=1000: the caption line owns the band below it and
    # the presenter stands in the bottom-right corner.
    # Fills the band between the title and the caption line. The drawing is
    # the subject of the shot, so it gets the space rather than sitting in a
    # corner of it.
    ground_y, wall_x, rise = 930, 690, 610
    run = round(rise * out / up)
    top = (wall_x, ground_y - rise)
    base_x = wall_x - run
    angle = math.degrees(math.atan2(rise, run))

    backdrop = Image.new("RGB", (WIDTH * SS, HEIGHT * SS), BG_TOP)
    bd = ImageDraw.Draw(backdrop)
    for y in range(0, HEIGHT * SS, 4):
        k = y / (HEIGHT * SS)
        bd.line([(0, y), (WIDTH * SS, y)],
                fill=tuple(round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * k) for i in range(3)),
                width=4)

    frames = max(1, round(duration * fps))
    with VideoWriter(dest, fps) as writer:
        for n in range(frames):
            t = n / fps
            canvas = backdrop.copy()
            d = ImageDraw.Draw(canvas)
            def s(v):
                return v * SS

            fade = _phase(t, 0.0, 0.30)
            if fade > 0.01:
                d.text((s(96), s(148)), "THE RULE", font=kicker,
                       fill=tuple(round(c * fade) for c in HI_VIS[:3]))
                d.text((s(96), s(196)), f"{up} : {out}", font=title,
                       fill=tuple(round(c * fade) for c in INK))

            g = _phase(t, at_structure, 0.40)
            if g > 0.01:
                span = 780 * g
                d.line([(s(190), s(ground_y)), (s(190 + span), s(ground_y))],
                       fill=GROUND, width=s(6))
                _hatch(d, s(198), s(ground_y), s(190 + span), 0,
                       spacing=s(36), length=s(19), colour=(58, 63, 72))
            w = _phase(t, at_structure + 0.15, 0.40)
            if w > 0.01:
                d.line([(s(wall_x), s(ground_y)), (s(wall_x), s(ground_y - 690 * w))],
                       fill=GROUND, width=s(6))
                _hatch(d, s(wall_x + 24), s(ground_y - 690 * w), 0, s(ground_y),
                       spacing=s(36), length=s(-19), colour=(58, 63, 72), vertical=True)

            swing = _phase(t, at_ladder, 0.75)
            if swing > 0.01:
                bx = wall_x - run * swing
                # Angle arc, so the ratio reads as a geometry not a slogan.
                if swing > 0.9:
                    r = 150
                    d.arc([s(bx - r), s(ground_y - r), s(bx + r), s(ground_y + r)],
                          start=-angle, end=0, fill=(126, 134, 146), width=s(4))
                    d.text((s(bx + 46), s(ground_y - 76)), f"{angle:.0f}\u00b0",
                           font=small, fill=(158, 166, 178))
                _ladder(d, (s(bx), s(ground_y)), (s(top[0]), s(top[1])),
                        width=s(86), colour=INK, rail=s(8), rung_gap=s(76))

            r = _phase(t, at_rise, 0.45)
            if r > 0.01:
                x = 812
                span = (ground_y - top[1]) * r
                d.line([(s(x), s(ground_y)), (s(x), s(ground_y - span))],
                       fill=HI_VIS[:3], width=s(5))
                d.line([(s(x - 20), s(ground_y)), (s(x + 20), s(ground_y))],
                       fill=HI_VIS[:3], width=s(5))
                if r > 0.95:
                    _arrow(d, (s(x), s(top[1])), (0, -1), size=s(20), colour=HI_VIS[:3])
                    d.text((s(x + 34), s((ground_y + top[1]) / 2 - 50)), str(up),
                           font=label, fill=HI_VIS[:3])

            ru = _phase(t, at_run, 0.45)
            if ru > 0.01:
                y = ground_y + 62
                span = run * ru
                d.line([(s(base_x), s(y)), (s(base_x + span), s(y))],
                       fill=HI_VIS[:3], width=s(5))
                d.line([(s(base_x), s(y - 18)), (s(base_x), s(y + 18))],
                       fill=HI_VIS[:3], width=s(5))
                if ru > 0.95:
                    _arrow(d, (s(wall_x), s(y)), (1, 0), size=s(20), colour=HI_VIS[:3])
                    d.text((s((base_x + wall_x) / 2 - 14), s(y + 26)), str(out),
                           font=label, fill=HI_VIS[:3])

            cap = _phase(t, at_run + 0.30, 0.40)
            if cap > 0.01:
                d.text((s(96), s(356)), f"{up} up, {out} out", font=small,
                       fill=tuple(round(DIM[i] + (INK[i] - DIM[i]) * cap) for i in range(3)))

            writer.write(canvas.resize((WIDTH, HEIGHT), Image.LANCZOS))

    return dest
