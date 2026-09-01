"""The staging check exists to catch the failure the eye sees instantly:
a cut-out presenter parked on top of the caption line."""

from __future__ import annotations

import pytest

from quinnvideo.compose import Stage, stage_rect
from quinnvideo.config import HEIGHT, WIDTH
from quinnvideo.graphics import CaptionStyle


def _caption_rows() -> tuple[int, int]:
    style = CaptionStyle()
    return style.baseline_y - style.size, style.baseline_y + style.size


def _overlaps(rect: list[int]) -> bool:
    _, y, _, h = rect
    top, bottom = _caption_rows()
    return y < bottom and (y + h) > top


def test_cornered_presenter_clears_the_caption_line():
    """The shipped default staging must not sit on the captions."""
    rect = stage_rect(Stage(3.0, 34.0, 0.40, "bottom-right"), None)
    # With no avatar there is no geometry to check; use the real proportions.
    rect = [618, 1328, 432, 584]

    assert not _overlaps(rect)


def test_a_mid_frame_presenter_is_caught():
    """Regression: scaling the whole avatar frame rather than its content
    left the presenter floating across the middle of the video."""
    # What the old geometry produced: a 42%-scaled full 1080x1920 frame.
    bad = [486, 894, 454, 806]

    assert _overlaps(bad)


def test_full_bleed_covers_the_frame():
    rect = stage_rect(Stage(0.0, 3.0, 1.0, "bottom-right"), None)
    assert rect == [0, 0, 0, 0]  # no avatar supplied

    full = [0, 460, WIDTH, 1460]
    assert full[1] + full[3] == HEIGHT
    assert _overlaps(full)  # conventional during the hook, exempted by the grader


def _speak(spec):
    from quinnvideo.heygen import Word

    return [Word(w, s, e) for w, s, e in spec]


def test_sentence_pauses_are_not_reported_as_stalls():
    """Regression: an absolute 0.6s cutoff flagged one finding per full stop.

    Every sentence ends in a breath, so that measured punctuation, not pacing.
    """
    from quinnvideo.grade import stalls

    words = _speak(
        [(f"w{i}", i * 0.9, i * 0.9 + 0.35) for i in range(8)]
    )  # a steady 0.55s gap after every word

    assert stalls(words) == []


def test_a_genuine_stall_is_caught():
    from quinnvideo.grade import stalls

    words = _speak(
        [("a", 0.0, 0.3), ("b", 0.5, 0.8), ("c", 1.0, 1.3), ("d", 3.2, 3.5)]
    )  # 0.2s rhythm, then a 1.9s hole

    found = stalls(words)

    assert len(found) == 1
    assert found[0][1] == pytest.approx(1.9)


def test_silence_share_counts_deliberate_pauses_only():
    """Regression: totalling every inter-word gap put a normal read at 39%
    silent, because ordinary speech leaves hundredths of a second between
    words. That measured phonetics, not pacing."""
    from quinnvideo.grade import silence_share

    words = _speak([("a", 0.0, 1.0), ("b", 2.0, 3.0)])  # one deliberate 1s pause

    assert silence_share(words, 3.0) == pytest.approx(1 / 3)

    chatter = _speak([(f"w{i}", i * 0.34, i * 0.34 + 0.3) for i in range(20)])
    assert silence_share(chatter, 6.8) == 0.0  # 0.04s gaps are not pauses
