"""A stage must refuse to start if it cannot finish.

Without this a missing key surfaces several stages in as a ConfigError, and a
missing codec as an ffmpeg failure inside a filter graph — in both cases after
the expensive calls have already been made.
"""

from __future__ import annotations

import pytest

from quinnvideo import doctor
from quinnvideo.config import Keys

FULL = Keys(heygen="h", pexels="p", pixabay=None, fal="f", replicate=None)
NONE = Keys(heygen=None, pexels=None, pixabay=None, fal=None, replicate=None)


@pytest.fixture(autouse=True)
def _no_bypass(monkeypatch):
    monkeypatch.delenv("QUINN_SKIP_PREFLIGHT", raising=False)


def _run(command: str, keys: Keys, monkeypatch, *, toolchain_ok: bool = True) -> None:
    monkeypatch.setattr(doctor.Keys, "load", classmethod(lambda _cls: keys))
    if toolchain_ok:
        ok = [doctor.Check("ffmpeg", True, "fine")]
        monkeypatch.setattr(doctor, "check_ffmpeg", lambda: ok)
        monkeypatch.setattr(doctor, "check_fonts", lambda: ok)
    doctor.preflight(command)


def test_narrate_without_a_heygen_key_stops_immediately(monkeypatch):
    with pytest.raises(doctor.NotReadyError, match="HEYGEN_API_KEY"):
        _run("narrate", NONE, monkeypatch)


def test_broll_asks_for_pexels_not_heygen(monkeypatch):
    """Each stage checks only what it uses; build should never demand a
    HeyGen key it will not touch."""
    only_heygen = Keys(heygen="h", pexels=None, pixabay=None, fal=None, replicate=None)

    with pytest.raises(doctor.NotReadyError, match="PEXELS_API_KEY"):
        _run("broll", only_heygen, monkeypatch)


def test_build_does_not_require_any_api_key(monkeypatch):
    _run("build", NONE, monkeypatch)  # ffmpeg and fonts only


def test_build_stops_when_the_toolchain_is_missing(monkeypatch):
    monkeypatch.setattr(doctor.Keys, "load", classmethod(lambda _cls: FULL))
    monkeypatch.setattr(
        doctor, "check_ffmpeg", lambda: [doctor.Check("ffmpeg", False, "not found")]
    )
    monkeypatch.setattr(doctor, "check_fonts", lambda: [doctor.Check("font", True, "ok")])

    with pytest.raises(doctor.NotReadyError, match="brew install ffmpeg"):
        doctor.preflight("build")


def test_stages_that_need_nothing_always_pass(monkeypatch):
    # `init` is deliberately absent: it gates the whole pipeline, because a
    # storyboard you cannot render is wasted work.
    for command in ("doctor", "fonts", "check", "plan", "status"):
        _run(command, NONE, monkeypatch, toolchain_ok=False)


def test_the_message_names_the_fix_not_just_the_fault(monkeypatch):
    with pytest.raises(doctor.NotReadyError) as caught:
        _run("candidates", NONE, monkeypatch)

    message = str(caught.value)
    assert "FAL_KEY" in message
    assert "set FAL_KEY in .env" in message
    assert "quinn-video doctor" in message


def test_the_bypass_works(monkeypatch):
    monkeypatch.setenv("QUINN_SKIP_PREFLIGHT", "1")
    monkeypatch.setattr(doctor.Keys, "load", classmethod(lambda _cls: NONE))

    doctor.preflight("narrate")


def test_every_paid_stage_is_covered():
    """Anything that spends money must be in the table."""
    for command in ("narrate", "avatar", "probe", "candidates"):
        assert doctor.NEEDS.get(command), f"{command} has no preflight"


def test_init_checks_the_whole_pipeline_not_just_itself(monkeypatch):
    """A run that cannot finish should not be started.

    Regression: a real run found the credentials missing, wrote a full
    storyboard anyway, and reported the blocker two and a half minutes later.
    """
    only_toolchain = Keys(heygen=None, pexels=None, pixabay=None, fal=None, replicate=None)

    with pytest.raises(doctor.NotReadyError) as caught:
        _run("init", only_toolchain, monkeypatch)

    message = str(caught.value)
    assert "HEYGEN_API_KEY" in message
    assert "PEXELS_API_KEY" in message
    assert "wasted work" in message
    assert "--draft" in message


def test_draft_bypasses_the_init_check(monkeypatch):
    monkeypatch.setattr(doctor.Keys, "load", classmethod(lambda _cls: NONE))

    doctor.preflight("init", bypass=True)
