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


def test_the_cut_fingerprint_notices_a_swapped_shot():
    """Regression: the b-roll base was cached by existence alone, so replacing
    a clip rebuilt nothing and the finished video kept the old footage."""
    from pathlib import Path

    from quinnvideo.compose import Segment
    from quinnvideo.pipeline import _cut_fingerprint

    a = [Segment(Path("one.mp4"), 0.0, 2.0), Segment(Path("two.mp4"), 2.0, 2.0)]
    b = [Segment(Path("one.mp4"), 0.0, 2.0), Segment(Path("three.mp4"), 2.0, 2.0)]
    reordered = [a[1], a[0]]

    assert _cut_fingerprint(a) == _cut_fingerprint(list(a))
    assert _cut_fingerprint(a) != _cut_fingerprint(b)
    assert _cut_fingerprint(a) != _cut_fingerprint(reordered)


def test_a_layer_built_from_an_old_script_is_a_blocker(tmp_path, monkeypatch):
    """Regression: a video shipped with the captions of an earlier draft over
    the narration of a later one.

    ``overlay.mov`` was cached on existence, so re-narrating rebuilt the audio
    and the avatar but kept the old caption layer. Every frame looked right on
    its own and the grader passed it. The layers are all cut from the same
    word timestamps, so a duration that disagrees with the narration means the
    layer was built from a different script.
    """
    from quinnvideo import grade as grade_module
    from quinnvideo.grade import _layer_findings
    from quinnvideo.runs import Run

    run = Run(tmp_path / "run")
    run.overlay.parent.mkdir(parents=True, exist_ok=True)
    for path in (run.avatar, run.overlay, run.base):
        path.write_text("x")

    durations = {run.avatar: 39.1, run.overlay: 25.2, run.base: 38.8}
    monkeypatch.setattr(grade_module.ff, "duration", lambda p: durations[p])

    findings = _layer_findings(run, 39.08)

    assert [f.severity for f in findings] == ["blocker"]
    assert "overlay.mov" in findings[0].criterion
    assert "25.2s against 39.1s" in findings[0].detail


def test_layers_that_agree_with_the_narration_pass(tmp_path, monkeypatch):
    from quinnvideo import grade as grade_module
    from quinnvideo.grade import _layer_findings
    from quinnvideo.runs import Run

    run = Run(tmp_path / "run")
    run.overlay.parent.mkdir(parents=True, exist_ok=True)
    for path in (run.avatar, run.overlay, run.base):
        path.write_text("x")

    durations = {run.avatar: 39.09, run.overlay: 39.07, run.base: 38.77}
    monkeypatch.setattr(grade_module.ff, "duration", lambda p: durations[p])

    assert _layer_findings(run, 39.08) == []


def test_a_held_final_frame_is_not_a_sync_error(tmp_path, monkeypatch):
    """Regression: the video holds its last frame past the final syllable, so
    measuring the layers against the finished runtime reported every one of
    them as a second short. They are cut to the narration, not the file."""
    from quinnvideo import grade as grade_module
    from quinnvideo.grade import _layer_findings
    from quinnvideo.runs import Run

    run = Run(tmp_path / "run")
    run.overlay.parent.mkdir(parents=True, exist_ok=True)
    for path in (run.avatar, run.overlay, run.base):
        path.write_text("x")

    narration, runtime = 31.74, 32.44  # 0.7s hold
    durations = {run.avatar: 31.77, run.overlay: 31.72, run.base: 31.53}
    monkeypatch.setattr(grade_module.ff, "duration", lambda p: durations[p])

    assert _layer_findings(run, narration) == []
    assert _layer_findings(run, runtime)  # what the old reference did
