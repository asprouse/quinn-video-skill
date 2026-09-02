"""The ledger makes assertions visible; it does not verify them.

Nothing in this pipeline checks whether a script is true. What these tests
pin down is that a script cannot quietly assert something the ledger never
mentions -- that check is mechanical, so it cannot be argued with, which is
what stops the ledger becoming optional.
"""

from __future__ import annotations

import pytest

from quinnvideo.claims import assertions, audit, ledger
from quinnvideo.storyboard import Beat, Claim, Storyboard, Visual


def _beat(id: int, narration: str, overlay=None) -> Beat:
    return Beat(
        id=id,
        narration=narration,
        visual=Visual(intent="a worker lifting a box", queries=["warehouse lifting"]),
        overlay=overlay,
    )


def _board(beats: list[Beat], claims: list[Claim] | None = None) -> Storyboard:
    return Storyboard(topic="lifting safety", beats=beats, claims=claims or [])


# --- detection ---------------------------------------------------------------


def test_numbers_spelled_out_are_found():
    """Scripts spell numbers out because the speech engine reads digits
    unpredictably, so the detector has to read them the same way."""
    assert assertions("roughly ten times its weight") == ["ten"]
    assert assertions("a twenty pound box") == ["twenty"]
    assert assertions("loads your spine like two hundred") == ["two hundred"]


def test_a_longer_number_does_not_swallow_a_later_separate_one():
    """Regression: deduping by text meant "four hundred" hid the "Four" in
    "Four figures" -- two distinct claims, one of them invisible."""
    assert assertions("Not four hundred horsepower. Four figures.") == [
        "four hundred",
        "Four",
    ]


def test_a_repeated_assertion_is_counted_once():
    assert assertions("entered twenty nine races and won twenty nine races") == ["twenty nine"]


def test_a_ratio_is_one_assertion_not_its_digits():
    assert assertions("the 4-to-1 rule") == ["4-to-1"]


def test_named_standards_and_universals_are_found():
    assert "three points of contact" in assertions("keep three points of contact")
    assert "always" in assertions("You should always tie off.")


def test_ordinary_instruction_is_not_an_assertion():
    """Over-detection costs a ledger line; noise on every beat costs the
    check its credibility."""
    assert assertions("Bring it in. Load against your chest, elbows tucked.") == []


# --- coverage ----------------------------------------------------------------


def test_an_unledgered_number_blocks():
    issues = audit(_board([_beat(1, "Ladders are useful."), _beat(2, "ten times its weight")]))

    blockers = [i for i in issues if i.severity == "blocker"]
    assert len(blockers) == 1
    assert blockers[0].beat == 2


def test_a_ledgered_number_passes():
    board = _board(
        [_beat(1, "Ladders are useful."), _beat(2, "roughly ten times its weight")],
        [Claim(beat=2, text="ten times through the lower back", status="estimate")],
    )
    assert audit(board) == []


def test_an_overlay_asserts_too():
    """A card reading "1000+ hp" commits to a number just as hard as the
    narration -- harder, since it stays on screen while the voice moves on."""
    from quinnvideo.storyboard import Overlay

    board = _board(
        [
            _beat(1, "It swallows boost."),
            _beat(2, "It goes further.", Overlay(kind="stat", text="1000+ hp")),
        ]
    )
    blockers = [i for i in audit(board) if i.severity == "blocker"]
    assert [b.beat for b in blockers] == [2]


# --- provenance --------------------------------------------------------------


def test_calling_a_claim_established_requires_naming_what_establishes_it():
    board = _board(
        [_beat(1, "Ladders are useful."), _beat(2, "the 4-to-1 rule")],
        [Claim(beat=2, text="ladders are set at a four to one ratio", status="established")],
    )
    blockers = [i for i in audit(board) if i.severity == "blocker"]
    assert len(blockers) == 1
    assert "no source" in blockers[0].detail


def test_an_estimate_stated_flatly_is_flagged():
    """The rubric rewards punchy specificity and the guidance says "give the
    real number"; together they select for confident round figures. An
    approximation has to read as one."""
    board = _board(
        [_beat(1, "Ladders are useful."), _beat(2, "ten times its weight")],
        [Claim(beat=2, text="ten times through the lower back", status="estimate")],
    )
    warnings = [i for i in audit(board) if i.severity == "warn"]
    assert any("states it flatly" in w.detail for w in warnings)


def test_a_hedged_estimate_is_not_flagged():
    board = _board(
        [_beat(1, "Ladders are useful."), _beat(2, "roughly ten times its weight")],
        [Claim(beat=2, text="ten times through the lower back", status="estimate")],
    )
    assert not [i for i in audit(board) if "states it flatly" in i.detail]


def test_unverified_claims_are_surfaced():
    board = _board(
        [_beat(1, "Ladders are useful."), _beat(2, "ten times its weight")],
        [Claim(beat=2, text="ten times through the lower back", status="unverified")],
    )
    assert any("recall alone" in i.detail for i in audit(board))


def test_a_claim_on_a_beat_that_does_not_exist_blocks():
    board = _board(
        [_beat(1, "Ladders are useful."), _beat(2, "ten times its weight")],
        [Claim(beat=9, text="ten times through the lower back", status="estimate")],
    )
    assert any("does not exist" in i.detail for i in audit(board))


# --- presentation ------------------------------------------------------------


def test_the_ledger_puts_the_riskiest_claims_first():
    board = _board(
        [_beat(1, "Ladders are useful."), _beat(2, "roughly ten times its weight")],
        [
            Claim(beat=2, text="derived arithmetic", status="illustrative"),
            Claim(beat=2, text="from recall alone", status="unverified"),
        ],
    )
    rendered = ledger(board)
    assert rendered.index("from recall alone") < rendered.index("derived arithmetic")


def test_an_empty_ledger_says_so():
    assert "none declared" in ledger(_board([_beat(1, "Bring it in."), _beat(2, "Elbows tucked.")]))


@pytest.mark.parametrize("text", ["a 40% drop", "it is 12x worse", "30 percent"])
def test_digit_forms_are_found(text):
    assert assertions(text)


# --- provenance quality ------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("https://www.cdc.gov/mmwr/preview/mmwrhtml/mm6316a2.htm", "primary"),
        ("bls.gov CFOI 2023", "primary"),
        ("https://pmc.ncbi.nlm.nih.gov/articles/PMC4584774", "primary"),
        ("a stanford.edu study", "primary"),
        ("https://en.wikipedia.org/wiki/Nissan_Skyline", "secondary"),
        ("Wikipedia", "secondary"),
        ("silodrome.com", "secondary"),
        ("NIOSH lifting equation", "unattributed"),
        ("", "unattributed"),
    ],
)
def test_source_quality_is_about_where_not_whether(source, kind):
    from quinnvideo.claims import source_kind

    assert source_kind(source) == kind


def test_a_patent_is_a_filing_not_a_finding():
    """uspto.gov is a .gov and would otherwise pass as primary. Restricting a
    biomechanics search to government domains returned mostly patents."""
    from quinnvideo.claims import source_kind

    assert source_kind("https://image-ppubs.uspto.gov/x/10034810") == "secondary"
    assert source_kind("https://patents.google.com/patent/US123") == "secondary"


def test_wikipedia_followed_to_a_primary_source_counts():
    """Following an encyclopedia out to its references is the path a reviewer
    is supposed to take, so it must not be penalised."""
    from quinnvideo.claims import source_kind

    assert source_kind("Wikipedia, followed to https://www.cdc.gov/mmwr/x.htm") == "primary"


def test_established_on_a_secondary_source_blocks():
    """The laundering guard: a search returning Wikipedia for a claim the
    model already believed has added a citation and no information, and the
    citation is what makes it survive review."""
    board = _board(
        [_beat(1, "Ladders are useful."), _beat(2, "It won twenty nine races.")],
        [
            Claim(
                beat=2,
                text="twenty nine wins from twenty nine starts",
                status="established",
                source="https://en.wikipedia.org/wiki/Nissan_Skyline_GT-R",
            )
        ],
    )
    blockers = [i for i in audit(board) if i.severity == "blocker"]
    assert len(blockers) == 1
    assert "secondary source" in blockers[0].detail


def test_established_on_a_primary_source_passes():
    board = _board(
        [_beat(1, "Ladders are useful."), _beat(2, "It killed one hundred and thirteen workers.")],
        [
            Claim(
                beat=2,
                text="113 work-related ladder fall fatalities",
                status="established",
                source="https://www.cdc.gov/mmwr/preview/mmwrhtml/mm6316a2.htm",
            )
        ],
    )
    assert audit(board) == []


def test_the_worklist_only_lists_numeric_claims_needing_a_source():
    """Narrow on purpose: a number is what the script cannot hedge its way out
    of and what a primary source can actually settle."""
    from quinnvideo.claims import worklist

    board = _board(
        [_beat(1, "Bring it in close."), _beat(2, "roughly ten times its weight")],
        [
            Claim(beat=2, text="ten times through the lower back", status="estimate"),
            Claim(beat=2, text="derived arithmetic", status="illustrative"),
        ],
    )
    listed = worklist(board)
    assert "ten times through the lower back" in listed
    assert "derived arithmetic" not in listed


def test_the_worklist_goes_quiet_once_sourced():
    from quinnvideo.claims import worklist

    board = _board(
        [_beat(1, "Bring it in close."), _beat(2, "roughly ten times its weight")],
        [
            Claim(
                beat=2,
                text="ten times through the lower back",
                status="estimate",
                source="https://www.osha.gov/otm/section-7-ergonomics/chapter-1",
            )
        ],
    )
    assert "Nothing to check" in worklist(board)
