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

            writer.write(canvas.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS))

    return dest


def _tick(draw, frm, to, direction) -> None:
    """A thin extension line carrying a measurement out to its dimension.

    Starts just off the object and runs just past the dimension line, the way
    a drafted extension line does, so the offset reads as intentional.
    """
    fx, fy = frm
    tx_, ty_ = to
    draw.line([(fx - direction * 10 * SS, fy), (tx_ - direction * 12 * SS, ty_)],
              fill=(236, 240, 248, 150), width=2 * SS)


def render_ladder_annotation(
    photo: Path,
    dest: Path,
    duration: float,
    *,
    base: tuple[float, float],
    top: tuple[float, float],
    ratio: tuple[int, int] = (4, 1),
    fps: int = FPS,
    cues: dict[str, float] | None = None,
    push: float = 0.03,
) -> Path:
    """Annotate a real photograph with the ladder geometry.

    Drawing the rule on an actual ladder beats cutting away to a diagram on
    black: the video never leaves the world it is teaching about, and the
    viewer sees the ratio on the thing they will be standing on.

    ``base`` and ``top`` are the ladder's feet and its contact with the wall,
    in normalised 0-1 frame coordinates. They are read off the photograph by
    eye rather than detected, because a wrong anchor here would draw a
    confident annotation in the wrong place.
    """
    from PIL import Image, ImageDraw

    from .ff import VideoWriter

    up, out = ratio
    cues = cues or {}
    # No "structure" phase: the photograph supplies the wall and the ground.
    at_ladder = cues.get("ladder", 0.55)
    at_rise = cues.get("rise", 1.25)
    at_run = cues.get("run", 1.70)

    bx, by = base[0] * WIDTH * SS, base[1] * HEIGHT * SS
    tx, ty = top[0] * WIDTH * SS, top[1] * HEIGHT * SS
    corner = (tx, by)  # foot of the wall, directly below the top contact

    rise_px, run_px = abs(by - ty), abs(tx - bx)
    measured = rise_px / run_px if run_px else 0.0
    target = up / out
    if abs(measured - target) / target > 0.25:
        raise ValueError(
            f"the ladder in {photo.name} sits at {measured:.1f}:1, not {up}:{out}. "
            "Annotating it with the rule would teach the wrong angle — "
            "regenerate the photograph or correct the anchors."
        )

    angle = math.degrees(math.atan2(rise_px, run_px))
    direction = 1 if bx > tx else -1  # which side the feet stand on

    title = fonts.load(fonts.DISPLAY, 118 * SS)
    label = fonts.load(fonts.DISPLAY, 84 * SS)
    kicker = fonts.load(fonts.CAPTION, 32 * SS)

    # Scale-to-cover once, up front; every frame is a crop of this.
    source = Image.open(photo).convert("RGB")
    scale = max(WIDTH * SS / source.width, HEIGHT * SS / source.height)
    source = source.resize(
        (round(source.width * scale), round(source.height * scale)), Image.Resampling.LANCZOS
    )
    left = (source.width - WIDTH * SS) // 2
    top_off = (source.height - HEIGHT * SS) // 2
    source = source.crop((left, top_off, left + WIDTH * SS, top_off + HEIGHT * SS))

    # A gradient scrim at the top so the title holds against a bright wall.
    scrim = Image.new("L", (1, HEIGHT * SS))
    for y in range(HEIGHT * SS):
        scrim.putpixel((0, y), max(0, round(150 * (1 - y / (HEIGHT * SS * 0.42)))))
    scrim = scrim.resize((WIDTH * SS, HEIGHT * SS))
    source = Image.composite(Image.new("RGB", source.size, (8, 10, 14)), source, scrim)

    frames = max(1, round(duration * fps))
    with VideoWriter(dest, fps) as writer:
        for n in range(frames):
            t = n / fps
            canvas = source.copy()
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)

            fade = _phase(t, 0.0, 0.30)
            if fade > 0.01:
                d.text((96 * SS, 132 * SS), "THE RULE", font=kicker,
                       fill=(*HI_VIS[:3], round(255 * fade)))
                d.text((96 * SS, 180 * SS), f"{up} : {out}", font=title,
                       fill=(*INK, round(255 * fade)))

            # Nothing is drawn for the wall or the ground. The photograph has
            # both already, and an approximated line beside a real one reads
            # as a misprint -- which is how the first version looked, with a
            # grey construction line a few pixels off each bold dimension.

            trace = _phase(t, at_ladder, 0.60)
            if trace > 0.01:
                # Trace the ladder itself, so the eye is told what to look at.
                d.line([(bx, by), (bx + (tx - bx) * trace, by + (ty - by) * trace)],
                       fill=(*HI_VIS[:3], 235), width=7 * SS)
                if trace > 0.9:
                    r = 104 * SS
                    start, end = (180 - angle, 180) if direction > 0 else (0, angle)
                    d.arc([bx - r, by - r, bx + r, by + r], start=start, end=end,
                          fill=(235, 240, 248, 200), width=4 * SS)
                    # The arc alone. A degrees label has nowhere to sit here:
                    # inside the triangle it collides with the run dimension,
                    # outside it disappears behind the ladder's back legs. The
                    # ratio in the title is the number that matters anyway.

            r = _phase(t, at_rise, 0.45)
            if r > 0.01:
                # Drafting convention: the dimension stands clear of the
                # object and thin extension lines carry the measurement out to
                # it. Those ticks are what make the offset read as deliberate
                # rather than as a second, misaligned pass.
                x = tx - direction * 132 * SS
                _tick(d, (tx, ty), (x, ty), direction)
                _tick(d, (tx, by), (x, by), direction)
                d.line([(x, by), (x, by - (by - ty) * r)],
                       fill=(*HI_VIS[:3], 255), width=5 * SS)
                if r > 0.95:
                    _arrow(d, (x, ty), (0, -1), size=22 * SS, colour=(*HI_VIS[:3], 255))
                    _arrow(d, (x, by), (0, 1), size=22 * SS, colour=(*HI_VIS[:3], 255))
                    d.text((x - direction * 92 * SS, (by + ty) / 2 - 58 * SS), str(up),
                           font=label, fill=(*HI_VIS[:3], 255))

            ru = _phase(t, at_run, 0.45)
            if ru > 0.01:
                # On the ground line, inside the triangle the ladder makes
                # with the wall. That gap is what is being measured, it is
                # empty in the photograph, and it is the only room near the
                # feet -- anything below them falls off the frame.
                y = by - 6 * SS
                d.line([(corner[0], y), (corner[0] + (bx - corner[0]) * ru, y)],
                       fill=(*HI_VIS[:3], 255), width=5 * SS)
                if ru > 0.95:
                    _arrow(d, (bx, y), (direction, 0), size=20 * SS,
                           colour=(*HI_VIS[:3], 255))
                    _arrow(d, (corner[0], y), (-direction, 0), size=20 * SS,
                           colour=(*HI_VIS[:3], 255))
                    d.text(((bx + corner[0]) / 2 - 24 * SS, y - 150 * SS), str(out),
                           font=label, fill=(*HI_VIS[:3], 255))

            canvas = Image.alpha_composite(canvas.convert("RGBA"), layer).convert("RGB")

            # A slow push, so a still photograph does not sit dead on screen.
            if push:
                k = 1 + push * (t / max(duration, 0.001))
                cw, ch = round(WIDTH * SS / k), round(HEIGHT * SS / k)
                ox, oy = (WIDTH * SS - cw) // 2, (HEIGHT * SS - ch) // 2
                canvas = canvas.crop((ox, oy, ox + cw, oy + ch))

            writer.write(canvas.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS))

    return dest
