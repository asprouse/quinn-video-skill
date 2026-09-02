"""Choosing a presenter without reading the source to find out how.

The catalogue is ten thousand entries deep and labels gender inconsistently,
so both the filter and the shortlist need care: a literal match drops half the
pool, and ranking by name alone returns eight angles of one face.
"""

from __future__ import annotations

import pytest

from quinnvideo.doctor import normalise_gender


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("female", "female"),
        ("Woman", "female"),
        ("woman", "female"),
        ("male", "male"),
        ("Man", "male"),
        ("MALE", "male"),
        (" female ", "female"),
        (None, None),
        ("", None),
        ("nonbinary", None),
    ],
)
def test_gender_labels_are_normalised(raw, expected):
    """HeyGen uses "female" and "Woman" for the same thing across catalogue
    vintages, so filtering on the field literally silently drops half."""
    assert normalise_gender(raw) == expected


def test_a_heygen_url_yields_its_avatar_id():
    """The id sits in the path, with query junk after it."""
    from quinnvideo.doctor import _resolve

    ident, problem = _resolve(
        "https://app.heygen.com/avatar/my-avatars/"
        "f1884bb9341d4704b4b843e273130e1b?returnTo=%2Favatar%2Fmy-avatars"
    )
    assert ident == "f1884bb9341d4704b4b843e273130e1b"
    assert not problem


def test_a_url_without_an_id_is_rejected():
    from quinnvideo.doctor import _resolve

    ident, problem = _resolve("https://app.heygen.com/avatars")
    assert ident is None
    assert "no avatar id" in problem


def test_a_number_resolves_against_the_last_list(tmp_path, monkeypatch):
    """Nobody reads a 32-character hex string off a contact sheet; the number
    beside the face is what a person actually says."""
    import json

    from quinnvideo import doctor

    manifest = tmp_path / "presenters-last.json"
    manifest.write_text(
        json.dumps([{"n": 1, "id": "a" * 32, "name": "Maeve Therapy Coach 1"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(doctor, "_manifest_path", lambda: manifest)

    assert doctor._resolve("1")[0] == "a" * 32
    assert doctor._resolve("99")[1].startswith("there is no 99")
    assert doctor._resolve("Maeve")[0] == "a" * 32
    assert "nothing in the last list" in doctor._resolve("Zebediah")[1]


def test_the_probe_engine_is_one_the_avatar_supports():
    """Regression: the probe defaulted to avatar_iii because it is cheapest,
    but a custom avatar offers avatar_v and avatar_iv only. The probe then
    failed on the engine and reported that as a verdict on transparency --
    an unsupported engine and an unmattable avatar are different answers."""
    from quinnvideo.probe import cheapest_engine

    assert cheapest_engine({"supported_api_engines": ["avatar_v", "avatar_iv"]}) == "avatar_iv"
    assert (
        cheapest_engine({"supported_api_engines": ["avatar_v", "avatar_iv", "avatar_iii"]})
        == "avatar_iii"
    )
    assert cheapest_engine(None) == "avatar_iv"
    assert cheapest_engine({"supported_api_engines": []}) == "avatar_iv"
