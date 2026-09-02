"""Hold the script accountable for what it asserts.

These videos state things confidently -- a number, a ratio, a rule from a
standard -- and confidence is most of what makes them watchable. Nothing in
this pipeline checked any of it. Every mechanical check was about mechanics:
duration, sync, black frames, whether the footage matches the beat. The
script itself was taken on trust, and a wrong number in a safety video is
worse than a dull one.

There is a structural pull towards inventing statistics, too. The rubric
rewards punchy specificity and the script guidance says "give the real number
or no number", which together select for confident round figures -- exactly
where a fabricated one hides.

So: the storyboard carries a ledger of what it claims and where each claim
came from, and this module checks the ledger against the script. It does not
verify facts -- it cannot, and pretending otherwise would be worse than
nothing. What it does is make every assertion *visible* at the approval gate,
so the person paying for the render is deciding about a listed claim rather
than scanning prose for numbers.

The division of labour matters: judging what a claim is and where it came
from is the model's job, and detecting that a beat asserts something the
ledger never mentions is this module's. That check cannot be argued with,
which is what makes the ledger real rather than optional.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .storyboard import Storyboard

# Scripts spell numbers out, because the speech engine reads digits
# unpredictably. So the detector has to read them the same way.
_UNITS = [
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "million",
    "billion",
    "dozen",
    "half",
    "quarter",
]
# "one" is deliberately absent: it is far more often a pronoun ("no one",
# "the only one") than a quantity, and a real claim built on it almost always
# carries a second number that is caught anyway ("one in five").
_MULTIPLIERS = ["twice", "double", "triple", "tenfold", "fold"]

_NUMBER_WORD = re.compile(
    r"\b(?:" + "|".join(_UNITS + _MULTIPLIERS) + r")(?:\s+(?:" + "|".join(_UNITS) + r"))*\b",
    re.IGNORECASE,
)
_DIGITS = re.compile(r"\b\d[\d,]*(?:\.\d+)?(?:\s*(?:%|percent|x))?", re.IGNORECASE)
_RATIO = re.compile(r"\b\d+\s*[-\u2013\u2014]?\s*to\s*[-\u2013\u2014]?\s*\d+\b", re.IGNORECASE)
_STANDARD = re.compile(
    r"\b(?:OSHA|NIOSH|ANSI|ISO|ASTM|NFPA|CDC|WHO|EN\s?\d+|"
    r"three points of contact|four[- ]to[- ]one)\b",
    re.IGNORECASE,
)
_UNIVERSAL = re.compile(
    r"\b(?:always|never|every|guaranteed|proven|the only|leading cause|"
    r"most common|safest|deadliest|most dangerous)\b",
    re.IGNORECASE,
)

# A claim marked as an approximation has to read as one on screen.
_HEDGES = re.compile(
    r"\b(?:roughly|about|around|approximately|nearly|almost|up to|over|"
    r"more than|less than|as much as|typically|often|can|may|some|"
    r"order of|ballpark|or so)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Issue:
    severity: str  # "blocker" | "warn"
    beat: int | None
    detail: str
    fix: str


def assertions(text: str) -> list[str]:
    """The factual-looking spans in one line of narration.

    Deliberately over-eager. A false positive costs one ledger line saying
    "procedural, not a statistic"; a false negative is a number nobody looked
    at. Same trade as the cache fingerprints -- when in doubt, include it.
    """
    spans: list[tuple[int, int, str]] = []
    for pattern in (_RATIO, _STANDARD, _DIGITS, _NUMBER_WORD, _UNIVERSAL):
        spans.extend(
            (match.start(), match.end(), match.group(0).strip())
            for match in pattern.finditer(text)
            if match.group(0).strip()
        )

    # Drop a span only when an already-kept one covers the same position --
    # "four hundred" subsumes the "four" inside it, but must not swallow a
    # separate "Four figures" later in the line, which is its own assertion.
    kept: list[tuple[int, int, str]] = []
    for start, end, span in sorted(spans, key=lambda s: (s[0], -(s[1] - s[0]))):
        if not any(k_start <= start and end <= k_end for k_start, k_end, _ in kept):
            kept.append((start, end, span))
    # Collapse repeats: a line that says "twenty nine" twice makes one claim.
    seen: set[str] = set()
    unique: list[str] = []
    for _, _, span in sorted(kept):
        if span.lower() not in seen:
            seen.add(span.lower())
            unique.append(span)
    return unique


def audit(board: Storyboard) -> list[Issue]:
    """Check the ledger against what the script actually asserts."""
    issues: list[Issue] = []
    by_beat: dict[int, list] = {}
    for claim in board.claims:
        by_beat.setdefault(claim.beat, []).append(claim)

    known = {beat.id for beat in board.beats}
    for claim in board.claims:
        if claim.beat not in known:
            issues.append(
                Issue(
                    "blocker",
                    claim.beat,
                    f"the ledger has a claim on beat {claim.beat}, which does not exist",
                    "fix the beat number in claims[]",
                )
            )
        # Saying a claim is established is itself a claim. Name what establishes it.
        if claim.status == "established" and not claim.source.strip():
            issues.append(
                Issue(
                    "blocker",
                    claim.beat,
                    f'"{claim.text}" is marked established with no source',
                    'name the standard, agency or dataset it comes from, or mark it "unverified"',
                )
            )

    for beat in board.beats:
        # An overlay is an assertion the viewer reads off the screen, and a
        # card reading "1000+ hp" commits to a number just as hard as the
        # narration does -- harder, since it sits there while the voice moves on.
        spoken = beat.narration
        shown = beat.overlay.text if beat.overlay else ""
        spans = assertions(f"{spoken} {shown}".strip())
        claims = by_beat.get(beat.id, [])

        if spans and not claims:
            issues.append(
                Issue(
                    "blocker",
                    beat.id,
                    f"beat {beat.id} asserts {_quote(spans)} with nothing in the ledger",
                    "add a claims[] entry for it, or take the assertion out of the script",
                )
            )
        elif len(spans) > len(claims) + 1 and claims:
            issues.append(
                Issue(
                    "warn",
                    beat.id,
                    f"beat {beat.id} asserts {_quote(spans)} but the ledger covers {len(claims)}",
                    "check that every number in the line is accounted for",
                )
            )

        hedged = _HEDGES.search(beat.narration) is not None
        issues.extend(
            Issue(
                "warn",
                beat.id,
                f'"{claim.text}" is an estimate, but beat {beat.id} states it flatly',
                'hedge it in the narration ("roughly", "about") so the script '
                "does not claim more precision than the source has",
            )
            for claim in claims
            if claim.status == "estimate" and not hedged
        )

    unverified = [c for c in board.claims if c.status == "unverified"]
    if unverified:
        issues.append(
            Issue(
                "warn",
                None,
                f"{len(unverified)} claim(s) rest on recall alone, not a source",
                "confirm them against a source, hedge them, or cut them - "
                "these are the ones most likely to be confidently wrong",
            )
        )
    return issues


def _quote(spans: list[str]) -> str:
    shown = ", ".join(f'"{s}"' for s in spans[:4])
    return shown + (f" and {len(spans) - 4} more" if len(spans) > 4 else "")


def ledger(board: Storyboard) -> str:
    """The ledger as a person reads it at the approval gate."""
    if not board.claims:
        return "Claims\n  none declared"

    order = {"unverified": 0, "contested": 1, "estimate": 2, "established": 3, "illustrative": 4}
    lines = ["Claims"]
    for claim in sorted(board.claims, key=lambda c: (order.get(c.status, 9), c.beat)):
        lines.append(f"  [{claim.status:12}] beat {claim.beat}  {claim.text}")
        if claim.source.strip():
            lines.append(f"                 source: {claim.source}")
        if claim.note.strip():
            lines.append(f"                 note:   {claim.note}")
    return "\n".join(lines)
