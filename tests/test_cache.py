"""Artifacts must be invalidated by their inputs, not merely exist.

Two shipped defects came from existence-only caching: a re-narrated script
kept the previous avatar, and kept the previous caption layer.
"""

from __future__ import annotations

from quinnvideo.cache import fingerprint, is_fresh, mark, reuse


def test_a_file_without_a_fingerprint_is_never_fresh(tmp_path):
    """Anything built before fingerprinting, or by hand, must be rebuilt."""
    artifact = tmp_path / "thing.mp4"
    artifact.write_text("x")

    assert not is_fresh(artifact, fingerprint("a"))


def test_fresh_only_when_the_inputs_match(tmp_path):
    artifact = tmp_path / "thing.mp4"
    artifact.write_text("x")
    key = fingerprint("script text", "voice-1", 1.0)
    mark(artifact, key)

    assert is_fresh(artifact, key)
    assert not is_fresh(artifact, fingerprint("different text", "voice-1", 1.0))
    assert not is_fresh(artifact, fingerprint("script text", "voice-2", 1.0))
    assert not is_fresh(artifact, fingerprint("script text", "voice-1", 0.85))


def test_an_empty_file_is_not_fresh(tmp_path):
    artifact = tmp_path / "thing.mp4"
    artifact.write_bytes(b"")
    mark(artifact, fingerprint("a"))

    assert not is_fresh(artifact, fingerprint("a"))


def test_missing_file_is_not_fresh(tmp_path):
    assert not is_fresh(tmp_path / "absent.mp4", fingerprint("a"))


def test_force_always_rebuilds(tmp_path):
    artifact = tmp_path / "thing.mp4"
    artifact.write_text("x")
    key = fingerprint("a")
    mark(artifact, key)

    assert reuse(artifact, key)
    assert not reuse(artifact, key, force=True)


def test_fingerprints_ignore_argument_ordering_inside_dicts():
    assert fingerprint({"b": 2, "a": 1}) == fingerprint({"a": 1, "b": 2})


def test_fingerprints_respect_positional_order():
    assert fingerprint("a", "b") != fingerprint("b", "a")


def test_rewriting_the_script_invalidates_the_caption_layer(tmp_path):
    """Regression: a shipped video showed the captions of an earlier draft
    over the narration of a later one.

    ``overlay.mov`` was cached on existence, so re-narrating a run rebuilt the
    audio and the avatar but kept the old caption layer. Nothing failed and
    the grader passed it. The captions are drawn from word timestamps, so the
    timestamps must be what decides whether they are still valid.
    """
    overlay = tmp_path / "overlay.mov"
    overlay.write_text("captions for the first draft")

    draft = [("lift", 0.0, 0.4), ("with", 0.4, 0.7), ("your", 0.7, 0.9)]
    rewrite = [("bend", 0.0, 0.4), ("at", 0.4, 0.6), ("the", 0.6, 0.8)]

    mark(overlay, fingerprint(draft))

    assert is_fresh(overlay, fingerprint(draft))
    assert not is_fresh(overlay, fingerprint(rewrite))


def test_retiming_the_same_words_invalidates_the_caption_layer(tmp_path):
    """Same words at a different speed still need redrawing -- captions are
    placed on the clock, not on the text."""
    overlay = tmp_path / "overlay.mov"
    overlay.write_text("x")

    slow = [("lift", 0.0, 0.5), ("safely", 0.5, 1.2)]
    fast = [("lift", 0.0, 0.4), ("safely", 0.4, 0.9)]

    mark(overlay, fingerprint(slow))
    assert not is_fresh(overlay, fingerprint(fast))
