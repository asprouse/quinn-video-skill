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


def test_the_shortlist_is_distinct_people_not_looks():
    """One person appears as dozens of looks. Eight angles of the same face is
    not a choice, so only the best-ranked look per group survives."""
    pool = [
        {"id": "a1", "name": "Alexis", "group_id": "g1", "status": "completed"},
        {"id": "a2", "name": "Alexis", "group_id": "g1", "status": "completed"},
        {"id": "a3", "name": "Alexis", "group_id": "g1", "status": "completed"},
        {"id": "b1", "name": "Brianna", "group_id": "g2", "status": "completed"},
    ]
    best: dict[str, dict] = {}
    for avatar in pool:
        best.setdefault(str(avatar["group_id"]), avatar)

    assert [a["id"] for a in best.values()] == ["a1", "b1"]
