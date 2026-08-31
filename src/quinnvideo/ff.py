"""Thin ffmpeg helpers.

Two jobs: run ffmpeg and report failures usefully, and let Python stream
rendered RGBA frames straight into an encoder without ever touching disk.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

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

    def __enter__(self) -> AlphaWriter:
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
        assert self._process and self._process.stdin
        self._process.stdin.write(image.tobytes())
        self.frames += 1

    def __exit__(self, *exc: object) -> None:
        assert self._process
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
