"""Assemble the finished video with ffmpeg.

Two passes rather than one heroic filter graph. Pass one builds the b-roll
base track; pass two lays the avatar, the caption/graphics layer, and the
audio over it. Splitting them keeps each graph small enough to read, and it
means a failure tells you *which half* broke -- and lets the grading loop
rebuild only the visual half without re-paying HeyGen for narration.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path

from . import ff
from .config import FPS, HEIGHT, SAFE_BOTTOM, SAFE_RIGHT, WIDTH


@dataclass
class Segment:
    """One b-roll shot and the slice of the timeline it covers."""

    source: Path
    start: float
    duration: float
    is_still: bool = False
    # Ken Burns direction for stills. Motion keeps a photograph from reading
    # as a dead frame in the middle of a fast-cut sequence.
    zoom_in: bool = True


@dataclass
class Stage:
    """Where the avatar sits during a stretch of the video.

    ``scale`` is a fraction of frame width; 1.0 is full-bleed. Cutting between
    stages rather than animating between them is deliberate -- a hard size
    change lands as an edit, and ffmpeg cannot animate a scale filter anyway.
    """

    start: float
    end: float
    scale: float
    anchor: str = "bottom-right"  # bottom-right | bottom-left | bottom-center

    def position(self) -> tuple[str, str]:
        """Overlay x/y expressions, kept clear of the platform UI."""
        margin = 36
        if self.scale >= 0.98:
            return "0", "H-h"  # full-bleed presenter, feet at the frame edge
        bottom = f"H-h-{SAFE_BOTTOM - 120}"
        if self.anchor == "bottom-left":
            return str(margin), bottom
        if self.anchor == "bottom-center":
            return "(W-w)/2", bottom
        return f"W-w-{SAFE_RIGHT - 60}", bottom


@dataclass
class Composition:
    segments: list[Segment]
    narration: Path
    duration: float
    avatar: Path | None = None
    overlay: Path | None = None
    music: Path | None = None
    stages: list[Stage] = field(default_factory=list)
    music_gain: float = 0.16


# --- pass one: the b-roll base -------------------------------------------


def build_base(comp: Composition, dest: Path) -> Path:
    """Concatenate the b-roll shots into a single full-length track."""
    if not comp.segments:
        raise ValueError("nothing to compose: no b-roll segments")

    args: list[str] = []
    for segment in comp.segments:
        if segment.is_still:
            # Deliberately a single frame, not a looped one: zoompan emits its
            # `d` frames for *every* frame it is fed, so handing it a looped
            # still multiplies the shot length by itself.
            args += ["-i", str(segment.source)]
        else:
            # Loop in case the stock clip is shorter than its slot, and cap
            # the input so we do not decode more than we use.
            args += [
                "-stream_loop", "-1",
                "-t", f"{segment.duration:.3f}",
                "-i", str(segment.source),
            ]

    chains = []
    labels = []
    for i, segment in enumerate(comp.segments):
        label = f"s{i}"
        labels.append(f"[{label}]")
        chains.append(_segment_chain(i, segment, label))

    graph = ";".join(chains)
    graph += f";{''.join(labels)}concat=n={len(comp.segments)}:v=1:a=0[base]"

    ff.run(
        args
        + [
            "-filter_complex", graph,
            "-map", "[base]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "18",  # this is an intermediate; keep generational loss low
            "-pix_fmt", "yuv420p",
            "-r", str(FPS),
            str(dest),
        ]
    )
    return dest


def _segment_chain(index: int, segment: Segment, label: str) -> str:
    """Scale-to-fill, crop to 9:16, and trim one shot to its slot.

    Stock footage is nearly always landscape, so 'cover' cropping is the only
    option that fills a vertical frame without pillarboxing.
    """
    frames = max(1, round(segment.duration * FPS))
    cover = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT}"
    )

    if segment.is_still:
        # One input frame in, `frames` frames out. zoompan needs the source
        # oversampled first or the zoom shimmers on high-contrast edges.
        direction = (
            f"1+0.12*on/{frames}" if segment.zoom_in else f"1.12-0.12*on/{frames}"
        )
        return (
            f"[{index}:v]{cover},scale={WIDTH * 2}:{HEIGHT * 2},"
            f"zoompan=z='{direction}':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
            f"trim=duration={segment.duration:.3f},setpts=PTS-STARTPTS,"
            f"setsar=1,format=yuv420p[{label}]"
        )

    return (
        f"[{index}:v]trim=duration={segment.duration:.3f},setpts=PTS-STARTPTS,"
        f"fps={FPS},{cover},setsar=1,format=yuv420p[{label}]"
    )


# --- pass two: the composite ---------------------------------------------


def build_final(comp: Composition, base: Path, dest: Path) -> Path:
    """Lay avatar, captions, and audio over the base track."""
    args = ["-i", str(base)]
    index = 1

    avatar_index = None
    if comp.avatar:
        # VP9 alpha has to be decoded by libvpx-vp9; the native decoder drops
        # the alpha plane and the avatar arrives as an opaque black box.
        args += ["-c:v", "libvpx-vp9", "-i", str(comp.avatar)]
        avatar_index = index
        index += 1

    overlay_index = None
    if comp.overlay:
        args += ["-i", str(comp.overlay)]
        overlay_index = index
        index += 1

    args += ["-i", str(comp.narration)]
    narration_index = index
    index += 1

    music_index = None
    if comp.music:
        args += ["-stream_loop", "-1", "-i", str(comp.music)]
        music_index = index
        index += 1

    chains: list[str] = []
    current = "[0:v]"

    if avatar_index is not None:
        chains += _avatar_chains(comp, avatar_index)
        for n, stage in enumerate(comp.stages or _default_stages(comp.duration)):
            x, y = stage.position()
            nxt = f"[av{n}]"
            chains.append(
                f"{current}[avs{n}]overlay=x={x}:y={y}:"
                f"enable='between(t,{stage.start:.3f},{stage.end:.3f})'"
                f":eof_action=pass{nxt}"
            )
            current = nxt

    if overlay_index is not None:
        chains.append(f"{current}[{overlay_index}:v]overlay=eof_action=pass[vout]")
    else:
        chains.append(f"{current}null[vout]")

    chains.append(_audio_chain(narration_index, music_index, comp.music_gain))

    ff.run(
        args
        + [
            "-filter_complex", ";".join(chains),
            "-map", "[vout]",
            "-map", "[aout]",
            "-t", f"{comp.duration:.3f}",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
            "-r", str(FPS),
            # Fast-start so the file plays before it finishes downloading.
            "-movflags", "+faststart",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            str(dest),
        ]
    )
    return dest


def _avatar_chains(comp: Composition, avatar_index: int) -> list[str]:
    """Pre-scale one copy of the avatar per staging size."""
    stages = comp.stages or _default_stages(comp.duration)
    chains = [f"[{avatar_index}:v]format=yuva420p,split={len(stages)}"
              + "".join(f"[avsrc{n}]" for n in range(len(stages)))]
    for n, stage in enumerate(stages):
        width = round(WIDTH * stage.scale / 2) * 2
        chains.append(f"[avsrc{n}]scale={width}:-2[avs{n}]")
    return chains


def _default_stages(duration: float) -> list[Stage]:
    """Presenter full-bleed for the hook, then out of the way.

    The first three seconds decide whether anyone watches the rest, and a
    face at full size is the strongest thing we have to hold them. After that
    the b-roll is doing the teaching, so the avatar shrinks into the corner.
    """
    hook = min(3.0, duration * 0.12)
    return [
        Stage(start=0.0, end=hook, scale=1.0),
        Stage(start=hook, end=duration, scale=0.42, anchor="bottom-right"),
    ]


def _audio_chain(narration_index: int, music_index: int | None, gain: float) -> str:
    """Narration at the front, music ducked underneath, output to broadcast loudness."""
    if music_index is None:
        return f"[{narration_index}:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"

    return (
        f"[{narration_index}:a]asplit=2[vo][key];"
        f"[{music_index}:a]volume={gain}[bed];"
        # Sidechain the bed against the voice so the music breathes in the
        # gaps instead of sitting at a constant level under the whole track.
        f"[bed][key]sidechaincompress=threshold=0.03:ratio=12:attack=8:release=320[duck];"
        f"[vo][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0"
        f",loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
    )


def describe(comp: Composition) -> str:
    """Human-readable plan, for logs and the scorecard."""
    lines = [f"{len(comp.segments)} shots over {comp.duration:.1f}s"]
    for i, segment in enumerate(comp.segments):
        kind = "still" if segment.is_still else "video"
        lines.append(
            f"  {i:2d}  {segment.start:5.2f}s +{segment.duration:4.2f}s  "
            f"{kind:5}  {shlex.quote(segment.source.name)}"
        )
    return "\n".join(lines)
