"""The storyboard is the contract; malformed ones must fail cheaply."""

from __future__ import annotations

import pytest

from quinnvideo.storyboard import Beat, Overlay, Storyboard, Visual, slug


def _beat(idx: int, narration: str, **kw) -> Beat:
    return Beat(
        id=idx,
        narration=narration,
        visual=Visual(intent="a worker on a ladder", queries=["ladder"]),
        **kw,
    )


def _board(**kw) -> Storyboard:
    return Storyboard(
        topic="ladder safety",
        beats=[_beat(1, "First line here."), _beat(2, "Second line here.")],
        **kw,
    )


def test_a_length_outside_the_brief_is_rejected():
    with pytest.raises(ValueError, match="target_seconds"):
        _board(target_seconds=90)


def test_a_beat_needs_at_least_one_real_query():
    with pytest.raises(ValueError, match="non-empty search query"):
        Visual(intent="a worker on a ladder", queries=["  "])


def test_narration_is_the_beats_joined():
    board = _board()

    assert board.narration == "First line here. Second line here."
    assert board.word_count == 6


def test_the_manifest_flags_a_hook_that_was_never_promoted():
    board = _board(hook_variants=["A different opening line.", "Another."], chosen_hook=0)

    notes = board.render_manifest()

    assert any(n.startswith("!") and "chosen_hook" in n for n in notes)


def test_the_manifest_accepts_a_promoted_hook():
    board = _board(hook_variants=["First line here.", "Another."], chosen_hook=0)

    assert any("variant 0 is in beat 1" in n for n in board.render_manifest())


def test_the_manifest_flags_emphasis_that_cannot_match():
    """Regression: emphasis on "161" never fired, because the narration says
    "a hundred and sixty-one" and matching is against spoken words."""
    board = Storyboard(
        topic="ladder safety",
        beats=[
            _beat(1, "Ladders killed a hundred and sixty-one workers.", emphasis=["161"]),
            _beat(2, "Second line here.", emphasis=["Second"]),
        ],
    )

    notes = board.render_manifest()

    assert any(n.startswith("!") and "161" in n for n in notes)
    assert any("emphasis on Second" in n for n in notes)


def test_a_generated_diagram_is_named_in_the_manifest():
    board = Storyboard(
        topic="ladder safety",
        beats=[
            _beat(1, "First line here.",
                  overlay=Overlay(kind="ladder-angle", text="4 : 1", ratio=(4, 1))),
            _beat(2, "Second line here."),
        ],
    )

    assert any("generated diagram" in n for n in board.render_manifest())


def test_slug_is_filesystem_safe():
    assert slug("Heat safety (staying cool!)") == "heat-safety-staying-cool"
    assert slug("///") == "video"
