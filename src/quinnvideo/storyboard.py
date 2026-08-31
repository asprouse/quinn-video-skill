"""The storyboard: the contract every pipeline stage reads and writes.

Claude authors this from a topic; the deterministic stages below it consume
it. Keeping one validated document in the middle is what stops the pipeline
turning into a chain of ad-hoc dict passing, and it is what makes a run
resumable -- the storyboard plus the run directory is the entire state.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .config import MAX_SECONDS, MIN_SECONDS, TARGET_SECONDS, TARGET_WPM


class Visual(BaseModel):
    """What should be on screen behind this line, and how to go find it."""

    intent: str = Field(
        ...,
        min_length=8,
        description="Plain description of the shot we want, used to judge candidates.",
    )
    queries: list[str] = Field(
        ...,
        min_length=1,
        max_length=4,
        description="Stock search terms, most specific first.",
    )
    prefer: Literal["video", "photo"] = "video"

    @field_validator("queries")
    @classmethod
    def _no_empty_queries(cls, value: list[str]) -> list[str]:
        cleaned = [q.strip() for q in value if q.strip()]
        if not cleaned:
            raise ValueError("at least one non-empty search query is required")
        return cleaned


class Overlay(BaseModel):
    """A graphic for this beat.

    ``ladder-angle`` generates an animated diagram instead of sourcing stock
    footage: the 4-to-1 rule is a statement about an angle, and no stock
    library has a clip of an angle. The others are typographic cards.
    """

    kind: Literal["stat", "label", "rule", "ladder-angle"]
    text: str = Field(..., max_length=48)
    ratio: tuple[int, int] = (4, 1)


class Beat(BaseModel):
    """One line of narration and the visual that carries it."""

    id: int
    narration: str = Field(..., min_length=3)
    visual: Visual
    emphasis: list[str] = Field(
        default_factory=list,
        description="Words to accent in the captions beyond the automatic highlight.",
    )
    overlay: Overlay | None = None

    @property
    def word_count(self) -> int:
        return len(self.narration.split())


class Storyboard(BaseModel):
    topic: str
    target_seconds: int = TARGET_SECONDS

    hook_variants: list[str] = Field(
        default_factory=list,
        description="Competing openings. Graded on text alone, before anything costs money.",
    )
    beats: list[Beat] = Field(..., min_length=2)
    cta: str = ""

    # Filled in by the pre-render grader once a hook wins.
    chosen_hook: int | None = None

    @model_validator(mode="after")
    def _check_length(self) -> Storyboard:
        if not (MIN_SECONDS <= self.target_seconds <= MAX_SECONDS):
            raise ValueError(
                f"target_seconds must be between {MIN_SECONDS} and {MAX_SECONDS}"
            )
        return self

    # --- derived -----------------------------------------------------------

    @property
    def narration(self) -> str:
        """The full script as one string, which is what gets sent to TTS."""
        return " ".join(beat.narration.strip() for beat in self.beats)

    @property
    def word_count(self) -> int:
        return len(self.narration.split())

    def estimated_seconds(self, wpm: int = TARGET_WPM) -> float:
        return self.word_count / wpm * 60

    def pacing_note(self, wpm: int = TARGET_WPM) -> str:
        estimate = self.estimated_seconds(wpm)
        if estimate < MIN_SECONDS:
            short_by = int((MIN_SECONDS - estimate) * wpm / 60)
            return f"too short: ~{estimate:.0f}s, add roughly {short_by} words"
        if estimate > MAX_SECONDS:
            long_by = int((estimate - MAX_SECONDS) * wpm / 60)
            return f"too long: ~{estimate:.0f}s, cut roughly {long_by} words"
        return f"on target: ~{estimate:.0f}s"

    # --- io ----------------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> Storyboard:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
        )
        return path


def slug(topic: str) -> str:
    """A filesystem-safe run name from a topic."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return cleaned[:48] or "video"
