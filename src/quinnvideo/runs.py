"""Run directories and stage caching.

Narration and avatar rendering cost real money and real minutes. Everything
a run produces is written to one directory and reused on the next attempt,
so a crash in compositing -- or a deliberate revision from the grading loop
-- never re-buys the audio.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from .config import RUNS
from .storyboard import Storyboard, slug

T = TypeVar("T")


@dataclass
class Run:
    """One attempt at one video."""

    directory: Path

    @classmethod
    def create(cls, topic: str, root: Path | None = None) -> Run:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        directory = (root or RUNS) / f"{slug(topic)}-{stamp}"
        directory.mkdir(parents=True, exist_ok=True)
        run = cls(directory)
        for sub in ("broll", "frames", "work"):
            (directory / sub).mkdir(exist_ok=True)
        return run

    @classmethod
    def open(cls, directory: Path) -> Run:
        if not directory.is_dir():
            raise FileNotFoundError(f"no run directory at {directory}")
        return cls(directory)

    @classmethod
    def latest(cls, root: Path | None = None) -> Run:
        root = root or RUNS
        candidates = sorted((p for p in root.glob("*") if p.is_dir()), reverse=True)
        if not candidates:
            raise FileNotFoundError(f"no runs under {root}")
        return cls(candidates[0])

    # --- well-known paths --------------------------------------------------

    @property
    def storyboard_path(self) -> Path:
        return self.directory / "storyboard.json"

    @property
    def speech_path(self) -> Path:
        return self.directory / "speech.json"

    @property
    def audio(self) -> Path:
        return self.directory / "narration.mp3"

    @property
    def avatar(self) -> Path:
        return self.directory / "avatar.webm"

    @property
    def overlay(self) -> Path:
        return self.directory / "work" / "overlay.mov"

    @property
    def base(self) -> Path:
        return self.directory / "work" / "base.mp4"

    @property
    def final(self) -> Path:
        return self.directory / "final.mp4"

    @property
    def report(self) -> Path:
        return self.directory / "report.html"

    @property
    def broll_dir(self) -> Path:
        return self.directory / "broll"

    @property
    def frames_dir(self) -> Path:
        return self.directory / "frames"

    # --- storyboard --------------------------------------------------------

    def storyboard(self) -> Storyboard:
        return Storyboard.load(self.storyboard_path)

    def save_storyboard(self, board: Storyboard) -> Path:
        return board.save(self.storyboard_path)

    # --- state -------------------------------------------------------------

    @property
    def state_path(self) -> Path:
        return self.directory / "state.json"

    def state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def update_state(self, **values: Any) -> dict[str, Any]:
        current = self.state()
        current.update(values)
        self.state_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        return current

    # --- caching -----------------------------------------------------------

    def cached(self, name: str, produce: Callable[[], T], *, force: bool = False) -> T:
        """Run ``produce`` once and remember its JSON-serialisable result.

        For stages whose output is a file, check the file instead -- this is
        for the metadata ones, like the speech response.
        """
        store = self.directory / "work" / f"{name}.json"
        if store.exists() and not force:
            return json.loads(store.read_text(encoding="utf-8"))  # type: ignore[return-value]
        value = produce()
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        return value

    def has(self, path: Path) -> bool:
        return path.exists() and path.stat().st_size > 0
