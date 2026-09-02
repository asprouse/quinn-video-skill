"""Reading a regulation, so a citation can be checked against what it says.

The failure this guards against is not an invented statistic -- it is a real
citation attached to a claim it does not support, which survives review
because the citation checks out at a glance. Retrieval cannot judge support;
it can only put the words in front of someone. So these tests pin down that
the words arrive intact and that a citation naming nothing is caught.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quinnvideo import cfr
from quinnvideo.cfr import CFRError, Citation, parse_citations

FIXTURE = Path(__file__).parent / "fixtures" / "cfr-part-9999.xml"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Never touch the network; eCFR is slow, rate-limited and sheds load."""

    def _fixture(_title, _part, **_kwargs):
        return FIXTURE

    monkeypatch.setattr(cfr, "fetch_part", _fixture)


# --- citations ---------------------------------------------------------------


def test_a_citation_with_subdivisions_is_parsed():
    (citation,) = parse_citations("29 CFR 1926.1053(b)(5)(i)")
    assert citation == Citation(29, "1926", "1926.1053", ("b", "5", "i"))
    assert str(citation) == "29 CFR 1926.1053(b)(5)(i)"


@pytest.mark.parametrize(
    "text",
    ["29 C.F.R. § 1926.1053", "29 CFR 1926.1053", "see 29 cfr 1926.1053 for the rule"],
)
def test_citation_spellings(text):
    assert parse_citations(text)[0].section == "1926.1053"


def test_a_bare_number_is_not_a_citation():
    """Guessing the title would invent provenance rather than record it."""
    assert parse_citations("the 1926.1053 rule") == []
    assert parse_citations("NIOSH lifting equation") == []


def test_several_citations_in_one_source():
    found = parse_citations("29 CFR 1926.1053 and 29 CFR 1910.23(b)")
    assert [c.section for c in found] == ["1926.1053", "1910.23"]


# --- reading -----------------------------------------------------------------


def test_a_section_yields_its_heading_and_paragraphs():
    head, paras = cfr.section(Citation(29, "9999", "9999.1"))
    assert head == "§ 9999.1 Ladders."
    assert len(paras) == 7


def test_paragraph_paths_follow_cfr_nesting():
    """CFR nests (a) -> (1) -> (i) -> (A), and a paragraph can carry several
    markers at once: "(5)(i) Non-self-supporting..."."""
    _, paras = cfr.section(Citation(29, "9999", "9999.1"))
    paths = [p.path for p in paras]
    assert paths[0] == ("a",)
    assert paths[1] == ("a", "1")
    assert paths[2] == ("a", "1", "i")
    assert paths[4] == ("b",)
    assert paths[5] == ("b", "5", "i")


def test_a_lone_i_after_a_digit_is_a_numeral_not_a_letter():
    """The only real ambiguity in CFR markers: (h) then (i) is a letter,
    (5) then (i) is a numeral."""
    _, paras = cfr.section(Citation(29, "9999", "9999.1"))
    assert ("a", "1", "i") in [p.path for p in paras]
    assert ("i",) not in [p.path for p in paras]


def test_a_subdivision_resolves_to_one_paragraph():
    citation = Citation(29, "9999", "9999.1", ("b", "5", "i"))
    _, paras = cfr.section(citation)
    hit = [p for p in paras if p.path == citation.subdivisions]
    assert len(hit) == 1
    assert "one-quarter of the working length" in hit[0].text


def test_a_section_that_does_not_exist_raises():
    with pytest.raises(CFRError, match="does not exist"):
        cfr.section(Citation(29, "9999", "9999.7"))


# --- searching ---------------------------------------------------------------


def test_a_phrase_is_found_with_its_section_and_context():
    hits = cfr.find(29, "9999", "points of contact")
    assert [section for section, _ in hits] == ["9999.2"]
    assert "drum flange" in hits[0][1]


def test_an_absent_phrase_returns_nothing():
    """The empty result is the useful one: it is what shows that a rule
    everybody 'knows' is in a standard is not in it."""
    assert cfr.find(29, "9999", "three points of contact") == []


# --- the ledger --------------------------------------------------------------


def _board(source: str):
    from quinnvideo.storyboard import Beat, Claim, Storyboard, Visual

    beat = Beat(
        id=1,
        narration="Set the base one foot out for every four feet up.",
        visual=Visual(intent="a worker setting a ladder", queries=["ladder"]),
    )
    second = beat.model_copy(update={"id": 2})
    return Storyboard(
        topic="ladder safety",
        beats=[beat, second],
        claims=[Claim(beat=1, text="the four to one ratio", status="established", source=source)],
    )


def test_a_citation_naming_nothing_blocks():
    from quinnvideo.claims import check_sources

    issues = check_sources(_board("29 CFR 9999.7"))
    assert [i.severity for i in issues] == ["blocker"]
    assert "does not resolve" in issues[0].detail


def test_a_citation_that_resolves_passes():
    from quinnvideo.claims import check_sources

    assert check_sources(_board("29 CFR 9999.1(b)(5)(i)")) == []


def test_a_subdivision_that_does_not_resolve_warns():
    """The section is real, so this is not a fabrication -- but the paragraph
    letters point somewhere that is not there."""
    from quinnvideo.claims import check_sources

    issues = check_sources(_board("29 CFR 9999.1(z)(9)"))
    assert [i.severity for i in issues] == ["warn"]


def test_a_non_cfr_source_is_left_alone():
    """Most sources are not regulations, and this checks regulations."""
    from quinnvideo.claims import check_sources

    assert check_sources(_board("NIOSH lifting equation")) == []
