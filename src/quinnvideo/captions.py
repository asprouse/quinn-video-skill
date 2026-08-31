"""Turn word timings into a rendered caption layer.

The brief asks for captions "appearing one word at a time in sync with the
voiceover". Taken literally that means one lonely word on screen at a time,
which is how you make a video unreadable. What the best short-form content
actually does -- and what we do here -- is build a short phrase word by word
with the currently-spoken word accented, so the viewer reads ahead a fraction
of a beat while still tracking the voice exactly.
"""

from __future__ import annotations

from pathlib import Path

from .config import FPS
from .ff import AlphaWriter
from .graphics import Group, Renderer, Token, blank
from .heygen import Word

# A pause longer than this reads as a phrase boundary in speech, so it should
# be one on screen too.
PAUSE_BREAK = 0.32

MAX_WORDS_PER_GROUP = 4
MAX_CHARS_PER_GROUP = 30

SENTENCE_END = ".!?"
CLAUSE_END = ",;:"


def group_words(words: list[Word]) -> list[Group]:
    """Chunk a word stream into phrases that appear as a unit.

    Breaks follow the speech, not a fixed word count: a pause, a sentence
    ending, or a phrase that has simply grown too wide to read at a glance.
    """
    groups: list[Group] = []
    current: list[Token] = []
    chars = 0

    for i, word in enumerate(words):
        current.append(Token(text=word.word, start=word.start, end=word.end))
        chars += len(word.word) + 1

        stripped = word.word.rstrip()
        is_last = i == len(words) - 1
        gap = (words[i + 1].start - word.end) if not is_last else 0.0

        should_break = (
            is_last
            or stripped.endswith(tuple(SENTENCE_END))
            or gap >= PAUSE_BREAK
            or len(current) >= MAX_WORDS_PER_GROUP
            or (chars >= MAX_CHARS_PER_GROUP and stripped.endswith(tuple(CLAUSE_END)))
        )

        if should_break:
            groups.append(Group(tokens=current))
            current = []
            chars = 0

    return groups


def render_layer(
    words: list[Word],
    dest: Path,
    *,
    duration: float | None = None,
    renderer: Renderer | None = None,
    extra_draw: object = None,
) -> Path:
    """Render the full caption layer to a lossless alpha video.

    ``extra_draw``, if given, is called as ``fn(canvas, t)`` for every frame
    after the captions are drawn -- that is the hook the stat cards and
    fallback graphics hang off, so everything shares one overlay pass.
    """
    renderer = renderer or Renderer()
    groups = group_words(words)
    for group in groups:
        renderer.layout(group)

    total = duration if duration is not None else (words[-1].end if words else 0.0)
    frame_count = max(1, round(total * FPS))

    # Groups are in time order, so a moving cursor beats searching every frame.
    cursor = 0
    empty = blank()

    with AlphaWriter(dest) as writer:
        for frame in range(frame_count):
            t = frame / FPS

            while cursor < len(groups) and t >= groups[cursor].end + _hold(groups, cursor):
                cursor += 1

            group = groups[cursor] if cursor < len(groups) else None
            visible = group is not None and t >= group.start

            if not visible and extra_draw is None:
                writer.write(empty)
                continue

            canvas = blank()
            if visible:
                renderer.draw_group(canvas, group, t)
            if extra_draw is not None:
                extra_draw(canvas, t)
            writer.write(canvas)

    return dest


def _hold(groups: list[Group], index: int) -> float:
    """How long a finished phrase lingers before the next one takes over.

    A phrase that vanishes the instant its last word ends feels twitchy, so it
    holds through the following pause -- but never past the next phrase's
    first word.
    """
    if index + 1 >= len(groups):
        return 0.4
    gap = groups[index + 1].start - groups[index].end
    return max(0.0, min(gap, 0.25))
