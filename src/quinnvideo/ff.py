"""Thin ffmpeg helpers.

Two jobs: run ffmpeg and report failures usefully, and let Python stream
rendered RGBA frames straight into an encoder without ever touching disk.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Self

from .config import FPS, HEIGHT, WIDTH


class FFmpegError(RuntimeError):
    pass


def binary(name: str = "ffmpeg") -> str:
    found = shutil.which(name)
    if not found:
        raise FFmpegError(f"{name} not found on PATH — `brew install ffmpeg`")
    return found


def run(args: Sequence[str], *, quiet: bool = True) -> None:
    """Run ffmpeg with the given arguments after the binary name."""
    cmd = [binary(), "-hide_banner", "-loglevel", "error" if quiet else "info", "-y", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-25:])
        raise FFmpegError(f"ffmpeg failed ({result.returncode}):\n{tail}\n\ncmd: {' '.join(cmd)}")


def probe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            binary("ffprobe"),
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise FFmpegError(f"ffprobe failed on {path}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def video_stream(path: Path) -> dict[str, Any]:
    for stream in probe(path)["streams"]:
        if stream.get("codec_type") == "video":
            return stream
    raise FFmpegError(f"{path} has no video stream")


def alpha_bbox(video: Path, samples: int = 5) -> tuple[int, int, int, int]:
    """Bounding box of the non-transparent content in an alpha video.

    A HeyGen avatar arrives as a full 1080x1920 frame with the presenter
    somewhere inside it and everything else transparent. Scaling that whole
    frame to put the presenter in a corner scales the empty space too, which
    leaves a bust floating in the middle of the video. So: find where the
    person actually is, and place *that*.

    Sampled across several frames and unioned, because the presenter moves.
    """
    from PIL import Image

    duration = globals()["duration"](video)
    left = top = 10**9
    right = bottom = 0

    for index in range(samples):
        at = duration * (index + 0.5) / samples
        frame = video.parent / f".bbox-{index}.png"
        run(["-c:v", "libvpx-vp9", "-ss", f"{at:.3f}", "-i", str(video),
             "-frames:v", "1", "-pix_fmt", "rgba", str(frame)])
        with Image.open(frame) as image:
            box = image.convert("RGBA").getchannel("A").getbbox()
        frame.unlink(missing_ok=True)
        if not box:
            continue
        left, top = min(left, box[0]), min(top, box[1])
        right, bottom = max(right, box[2]), max(bottom, box[3])

    if right <= left or bottom <= top:
        stream = video_stream(video)
        return 0, 0, int(stream["width"]), int(stream["height"])

    # Even widths and heights keep libx264 and the scaler happy.
    width = (right - left) // 2 * 2
    height = (bottom - top) // 2 * 2
    return left, top, max(2, width), max(2, height)


class VideoWriter:
    """Stream opaque RGB frames from Pillow into an h264 clip.

    Used for generated motion graphics, which sit in the b-roll track as
    ordinary shots rather than as an overlay -- so they behave like any other
    clip the cut list can schedule.
    """

    def __init__(self, dest: Path, fps: int = FPS) -> None:
        self.dest = dest
        self.fps = fps
        self._process: subprocess.Popen[bytes] | None = None
        self.frames = 0

    def __enter__(self) -> Self:
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        self._process = subprocess.Popen(
            [
                binary(), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{WIDTH}x{HEIGHT}", "-r", str(self.fps), "-i", "-",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", str(self.dest),
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return self

    def write(self, image: Any) -> None:
        if not (self._process and self._process.stdin):
            raise FFmpegError("writer used outside its context manager")
        self._process.stdin.write(image.tobytes())
        self.frames += 1

    def __exit__(self, *exc: object) -> None:
        if not self._process:
            raise FFmpegError("writer used outside its context manager")
        if self._process.stdin:
            self._process.stdin.close()
        stderr = self._process.stderr.read() if self._process.stderr else b""
        if self._process.wait() != 0:
            raise FFmpegError(
                f"graphic encode failed ({self._process.returncode}): "
                f"{stderr.decode(errors='replace').strip()[-1500:]}"
            )


class AlphaWriter:
    """Stream RGBA frames from Pillow into a lossless alpha-preserving file.

    QuickTime RLE rather than VP9: this is a scratch intermediate that gets
    composited immediately, so encode speed matters far more than file size,
    and lossless keeps caption edges crisp. Mostly-transparent frames -- which
    is nearly all of them -- run-length encode down to almost nothing anyway.
    """

    def __init__(self, dest: Path, fps: int = FPS) -> None:
        self.dest = dest
        self.fps = fps
        self._process: subprocess.Popen[bytes] | None = None
        self.frames = 0

    def __enter__(self) -> Self:
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        self._process = subprocess.Popen(
            [
                binary(), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "rawvideo",
                "-pix_fmt", "rgba",
                "-s", f"{WIDTH}x{HEIGHT}",
                "-r", str(self.fps),
                "-i", "-",
                "-c:v", "qtrle",
                "-pix_fmt", "argb",
                str(self.dest),
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return self

    def write(self, image: Any) -> None:
        if not (self._process and self._process.stdin):
            raise FFmpegError("writer used outside its context manager")
        self._process.stdin.write(image.tobytes())
        self.frames += 1

    def __exit__(self, *exc: object) -> None:
        if not self._process:
            raise FFmpegError("writer used outside its context manager")
        # Closing stdin is what tells ffmpeg the stream is done, so it has to
        # happen before we wait -- and rules out communicate(), which would
        # try to flush the handle we just closed.
        if self._process.stdin:
            self._process.stdin.close()
        stderr = self._process.stderr.read() if self._process.stderr else b""
        if self._process.wait() != 0:
            raise FFmpegError(
                f"alpha encode failed ({self._process.returncode}): "
                f"{stderr.decode(errors='replace').strip()[-1500:]}"
            )
