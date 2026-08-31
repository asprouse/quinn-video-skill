"""Caption grouping should follow the speech, not a fixed word count."""

from __future__ import annotations

import pytest

from quinnvideo.captions import MAX_WORDS_PER_GROUP, group_words
from quinnvideo.graphics import CaptionStyle, Renderer
from quinnvideo.heygen import Word


def _words(spec: list[tuple[str, float, float]]) -> list[Word]:
    return [Word(w, s, e) for w, s, e in spec]


def test_group_breaks_on_a_long_pause():
    words = _words([("stay", 0.0, 0.3), ("back", 0.3, 0.6), ("now", 1.4, 1.7)])

    groups = group_words(words)

    assert [[t.text for t in g.tokens] for g in groups] == [["stay", "back"], ["now"]]


def test_group_breaks_at_a_sentence_end():
    words = _words([("stop.", 0.0, 0.3), ("now", 0.32, 0.6)])

    groups = group_words(words)

    assert len(groups) == 2


def test_group_never_exceeds_the_width_cap():
    words = _words([(f"w{i}", i * 0.25, i * 0.25 + 0.2) for i in range(13)])

    groups = group_words(words)

    assert groups
    assert all(len(g.tokens) <= MAX_WORDS_PER_GROUP for g in groups)
    # Nothing is lost in the chunking.
    assert sum(len(g.tokens) for g in groups) == 13


def test_every_word_appears_exactly_once():
    words = _words([("a", 0.0, 0.2), ("b.", 0.2, 0.4), ("c", 0.9, 1.1), ("d", 1.1, 1.3)])

    groups = group_words(words)

    assert [t.text for g in groups for t in g.tokens] == ["a", "b.", "c", "d"]


def test_visible_line_stays_centred_as_the_phrase_grows():
    """A lone first word must not sit where a four-word phrase would start."""
    renderer = Renderer(CaptionStyle())
    words = _words([("only", 0.0, 0.3), ("six", 0.3, 0.6), ("feet", 0.6, 0.9)])
    group = group_words(words)[0]
    renderer.layout(group)

    from quinnvideo.config import WIDTH

    for count in (1, 2, 3):
        positions = group.layouts[count]
        left = positions[0][0]
        last = group.tokens[count - 1]
        right = positions[count - 1][0] + last.width
        assert (left + right) / 2 == pytest.approx(WIDTH / 2, abs=1.0)


def test_active_word_tracks_the_clock():
    words = _words([("one", 0.0, 0.3), ("two", 0.3, 0.6), ("three", 0.6, 0.9)])
    group = group_words(words)[0]

    assert group.active_index(0.1) == 0
    assert group.active_index(0.45) == 1
    assert group.active_index(0.85) == 2
    # After the phrase ends the last word stays lit rather than blinking off.
    assert group.active_index(5.0) == 2
