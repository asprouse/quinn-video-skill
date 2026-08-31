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


def render_ladder_angle(
    dest: Path,
    duration: float,
    *,
    fps: int = FPS,
    ratio: tuple[int, int] = (4, 1),
) -> Path:
    """Animate the 4-to-1 rule: a ladder swinging out to its correct angle."""
    from .ff import VideoWriter

    up, out = ratio
    title = fonts.load(fonts.DISPLAY, 132 * SS)
    label = fonts.load(fonts.DISPLAY, 74 * SS)
    kicker = fonts.load(fonts.CAPTION, 34 * SS)
    note = fonts.load(fonts.CAPTION, 33 * SS)

    # Everything lives above y=1000: the captions occupy the band below it and
    # the presenter sits in the bottom-right corner.
    ground_y = 900
    wall_x = 790
    rise = 560
    run = round(rise * out / up)
    top = (wall_x, ground_y - rise)
    base_final = (wall_x - run, ground_y)

    # Background gradient, drawn once.
    backdrop = Image.new("RGB", (WIDTH * SS, HEIGHT * SS), BG_TOP)
    bd = ImageDraw.Draw(backdrop)
    for y in range(0, HEIGHT * SS, 4):
        k = y / (HEIGHT * SS)
        bd.line(
            [(0, y), (WIDTH * SS, y)],
            fill=tuple(round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * k) for i in range(3)),
            width=4,
        )

    frames = max(1, round(duration * fps))
    with VideoWriter(dest, fps) as writer:
        for n in range(frames):
            t = n / fps
            canvas = backdrop.copy()
            d = ImageDraw.Draw(canvas)
            s = lambda v: v * SS  # noqa: E731 - local shorthand for readability

            # Title.
            fade = _phase(t, 0.0, 0.30)
            if fade > 0.01:
                d.text((s(110), s(150)), "THE RULE", font=kicker,
                       fill=tuple(round(c * fade) for c in HI_VIS[:3]))
                d.text((s(110), s(198)), f"{up} : {out}", font=title,
                       fill=tuple(round(c * fade) for c in INK))

            # Ground and wall.
            g = _phase(t, 0.15, 0.35)
            if g > 0.01:
                d.line([(s(180), s(ground_y)), (s(180 + (760 * g)), s(ground_y))],
                       fill=GROUND, width=7)
            w = _phase(t, 0.30, 0.35)
            if w > 0.01:
                d.line([(s(wall_x), s(ground_y)), (s(wall_x), s(ground_y - 640 * w))],
                       fill=GROUND, width=7)

            # The ladder swings out from flat against the wall to 4:1.
            swing = _phase(t, 0.55, 0.70)
            if swing > 0.01:
                bx = wall_x - run * swing
                _ladder(d, (s(bx), s(ground_y)), (s(top[0]), s(top[1])),
                        width=s(78), colour=INK, rail=s(7), rung_gap=s(74))

            # Rise dimension.
            r = _phase(t, 1.25, 0.40)
            if r > 0.01:
                _dimension(d, (s(892), s(ground_y)), (s(892), s(top[1])),
                           progress=r, colour=HI_VIS[:3], tick=s(24))
                if r > 0.55:
                    d.text((s(922), s((ground_y + top[1]) / 2 - 52)), str(up),
                           font=label, fill=HI_VIS[:3])

            # Run dimension.
            ru = _phase(t, 1.70, 0.40)
            if ru > 0.01:
                _dimension(d, (s(base_final[0]), s(ground_y + 58)),
                           (s(wall_x), s(ground_y + 58)),
                           progress=ru, colour=HI_VIS[:3], tick=s(20))
                if ru > 0.55:
                    d.text((s((base_final[0] + wall_x) / 2 - 16), s(ground_y + 82)),
                           str(out), font=label, fill=HI_VIS[:3])

            # The sentence the diagram is making.
            cap = _phase(t, 2.20, 0.40)
            if cap > 0.01:
                d.text((s(110), s(378)), f"{up} up, {out} out", font=note,
                       fill=tuple(round(DIM[i] + (INK[i] - DIM[i]) * cap) for i in range(3)))

            writer.write(canvas.resize((WIDTH, HEIGHT), Image.LANCZOS))

    return dest
