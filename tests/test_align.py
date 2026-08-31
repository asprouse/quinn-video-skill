"""Beats must land on the right seconds even when TTS retokenises the script."""

from __future__ import annotations

from itertools import pairwise

import pytest

from quinnvideo.align import align, normalise
from quinnvideo.heygen import Word
from quinnvideo.storyboard import Beat, Storyboard, Visual


def _visual() -> Visual:
    return Visual(intent="a worker on a ladder", queries=["ladder"])


def _board(*narrations: str) -> Storyboard:
    return Storyboard(
        topic="ladder safety",
        beats=[
            Beat(id=i + 1, narration=text, visual=_visual())
            for i, text in enumerate(narrations)
        ],
    )


def _speak(text: str, *, start: float = 0.0, pace: float = 0.3) -> list[Word]:
    words, t = [], start
    for token in text.split():
        words.append(Word(token, round(t, 3), round(t + pace, 3)))
        t += pace
    return words


def test_beats_align_to_their_own_words():
    board = _board("Ladders kill people.", "Set the base one foot out.")
    words = _speak("Ladders kill people. Set the base one foot out.")

    timings = align(board, words)

    assert [t.aligned for t in timings] == [True, True]
    assert timings[0].start == 0.0
    # Beat one owns three words; beat two starts where the fourth begins.
    assert timings[1].start == pytest.approx(0.9, abs=1e-6)
    assert timings[1].end == pytest.approx(words[-1].end)


def test_alignment_survives_numeral_expansion():
    """The script says "300"; the speech engine says "three hundred"."""
    board = _board("Every year 300 people die.", "Most fell six feet.")
    words = _speak("Every year three hundred people die. Most fell six feet.")

    timings = align(board, words)

    assert all(t.aligned for t in timings)
    # Beat two must start at "Most" (index 6), not at index 5 where a naive
    # word count would put it.
    assert timings[1].start == pytest.approx(words[6].start)


def test_unalignable_beat_is_interpolated_not_dropped():
    board = _board("Ladders kill people.", "Totally different unmatched text here.", "Stay safe.")
    words = _speak("Ladders kill people. xxx yyy zzz. Stay safe.")

    timings = align(board, words)

    assert len(timings) == 3
    assert timings[1].aligned is False
    # An estimated beat still gets a real, positive span.
    assert timings[1].duration > 0
    assert timings[1].start >= timings[0].start


def test_timeline_is_continuous_and_starts_at_zero():
    """No dead air: every beat hands straight over to the next."""
    board = _board("First line here.", "Second line here.", "Third line here.")
    words = _speak("First line here. Second line here. Third line here.")

    timings = align(board, words)

    assert timings[0].start == 0.0
    for current, following in pairwise(timings):
        assert current.end == pytest.approx(following.start)
    assert all(t.duration > 0 for t in timings)


def test_normalise_strips_punctuation_and_case():
    assert normalise("Ladder's,") == "ladder's"
    assert normalise("THREE.") == "three"
    assert normalise("--") == ""
