"""Map storyboard beats onto the narration timeline.

The b-roll cuts where the script changes subject, so every beat needs a start
and an end in seconds. We know the word timings and we know which words
belong to which beat -- but the two word lists do not always agree. Text to
speech expands numerals ("300" becomes "three hundred"), splits hyphenates,
and drops punctuation-only tokens, so a naive index-by-count drifts and the
b-roll starts cutting a beat early.

So: align greedily on normalised words, and fall back to a proportional split
for any beat the alignment could not place confidently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .heygen import Word
from .storyboard import Beat, Storyboard

_PUNCT = re.compile(r"[^\w']+")


def normalise(token: str) -> str:
    return _PUNCT.sub("", token.lower())


@dataclass
class BeatTiming:
    beat: Beat
    start: float
    end: float
    aligned: bool  # False means the span was estimated, not matched

    @property
    def duration(self) -> float:
        return self.end - self.start


def align(board: Storyboard, words: list[Word]) -> list[BeatTiming]:
    """Assign a time span to every beat."""
    if not words:
        raise ValueError("cannot align beats without word timestamps")

    spoken = [normalise(w.word) for w in words]
    timings: list[BeatTiming] = []
    cursor = 0

    for index, beat in enumerate(board.beats):
        expected = [normalise(t) for t in beat.narration.split() if normalise(t)]
        is_last = index == len(board.beats) - 1

        span = _consume(spoken, cursor, expected)

        if span is None:
            # Alignment lost the thread. Leave a placeholder and interpolate
            # once we know where the next beat actually starts.
            timings.append(BeatTiming(beat=beat, start=-1.0, end=-1.0, aligned=False))
            continue

        first_index, end_index = span
        if is_last:
            end_index = len(words)

        timings.append(
            BeatTiming(
                beat=beat,
                # Anchor to the first word we actually matched, not to the
                # cursor: anything between the two belongs to a preceding beat
                # the aligner could not place.
                start=words[first_index].start,
                end=words[end_index - 1].end,
                aligned=True,
            )
        )
        cursor = end_index

    _fill_gaps(timings, words)
    _close_seams(timings, words)
    return timings


def _consume(spoken: list[str], start: int, expected: list[str]) -> tuple[int, int] | None:
    """Find the span of spoken words covering one beat.

    Returns ``(first_matched, past_last_matched)``, or None if too little of
    the beat could be located to trust the result.

    Tolerates the speech engine emitting tokens the script does not have --
    numeral expansion is the common case, where "300" is spoken as "three
    hundred" and never matches literally. A script token that cannot be found
    within a short lookahead is skipped *without* moving the cursor, so one
    unmatchable word does not drag the alignment out of step for everything
    that follows it.
    """
    if not expected:
        return None

    max_skip = 4
    index = start
    first: int | None = None
    matched = 0

    for target in expected:
        probe = index
        skipped = 0
        while probe < len(spoken) and spoken[probe] != target and skipped < max_skip:
            probe += 1
            skipped += 1
        if probe < len(spoken) and spoken[probe] == target:
            if first is None:
                first = probe
            index = probe + 1
            matched += 1

    # Require most of the beat to have landed before trusting the span.
    if first is None or matched < max(1, int(len(expected) * 0.6)):
        return None
    return first, index


def _fill_gaps(timings: list[BeatTiming], words: list[Word]) -> None:
    """Interpolate spans for beats the aligner could not place.

    Unplaced beats are spread proportionally by word count across whatever
    time sits between their placed neighbours.
    """
    total_start = words[0].start
    total_end = words[-1].end

    index = 0
    while index < len(timings):
        if timings[index].aligned:
            index += 1
            continue

        run_start = index
        while index < len(timings) and not timings[index].aligned:
            index += 1
        run_end = index  # exclusive

        left = timings[run_start - 1].end if run_start > 0 else total_start
        right = timings[run_end].start if run_end < len(timings) else total_end
        span = max(0.0, right - left)

        weights = [max(1, t.beat.word_count) for t in timings[run_start:run_end]]
        total_weight = sum(weights)

        offset = left
        for timing, weight in zip(timings[run_start:run_end], weights):
            share = span * weight / total_weight
            timing.start = offset
            timing.end = offset + share
            offset += share


def _close_seams(timings: list[BeatTiming], words: list[Word]) -> None:
    """Remove the dead air between beats.

    A pause between sentences belongs to the shot that just played, not to a
    gap where the b-roll has nothing to show. Each beat is stretched to meet
    the next one so the visual track is continuous.
    """
    for current, following in zip(timings, timings[1:]):
        current.end = following.start
    if timings:
        timings[0].start = 0.0
        timings[-1].end = max(timings[-1].end, words[-1].end)
