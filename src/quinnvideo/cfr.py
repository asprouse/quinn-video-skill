"""Read the actual text of a federal regulation.

The claims ledger records where an assertion came from, but nothing checked
whether the source said what the claim said it said. That gap has a specific
failure mode, and it is worse than an invented statistic: a *real* citation
attached to a claim it does not support. It survives review because the
citation checks out at a glance.

This was not hypothetical. While writing the ledger's own documentation, the
4-to-1 ladder rule and "three points of contact" were cited together as OSHA
requirements. The first is real -- 29 CFR 1926.1053(b)(5)(i). The second does
not appear anywhere in 29 CFR 1926; the only "points of contact" in the whole
part is about crane rope drum flanges. Recall produced a plausible pairing and
recall could not catch it.

So: fetch the regulation and look. eCFR publishes the current text as XML,
free and without a key. This module does retrieval only -- it puts the
authoritative words in front of a reader and does not judge whether they
support a claim, because that is a reading question and this cannot read.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import CACHE

BASE = "https://www.ecfr.gov/api/versioner/v1"

# The API refuses an uncompressed response, with an error explaining as much.
# httpx negotiates gzip by default; this is here so a future rewrite onto a
# barer client does not rediscover it the hard way.
HEADERS = {"Accept-Encoding": "gzip, deflate"}


class CFRError(RuntimeError):
    pass


@dataclass(frozen=True)
class Citation:
    """A pointer into the Code of Federal Regulations."""

    title: int
    part: str
    section: str
    subdivisions: tuple[str, ...] = ()

    def __str__(self) -> str:
        subs = "".join(f"({s})" for s in self.subdivisions)
        return f"{self.title} CFR {self.section}{subs}"


# "29 CFR 1926.1053(b)(5)(i)", "29 C.F.R. 1926.1053", "OSHA 1926.1053(b)"
_CITATION = re.compile(
    r"\b(?:(?P<title>\d{1,2})\s*C\.?\s*F\.?\s*R\.?\s*(?:§+\s*)?)?"
    r"(?P<part>\d{1,4})\.(?P<sec>\d{1,5})"
    r"(?P<subs>(?:\s*\([0-9a-zA-Z]{1,4}\))*)",
    re.IGNORECASE,
)


def parse_citations(text: str) -> list[Citation]:
    """Every CFR citation in a source string.

    Requires an explicit title, because a bare "1926.1053" is not a citation
    -- it is a number that looks like one, and guessing the title would invent
    provenance rather than record it.
    """
    found: list[Citation] = []
    for match in _CITATION.finditer(text):
        if not match.group("title"):
            continue
        subs = tuple(re.findall(r"\(([0-9a-zA-Z]{1,4})\)", match.group("subs") or ""))
        citation = Citation(
            title=int(match.group("title")),
            part=match.group("part"),
            section=f"{match.group('part')}.{match.group('sec')}",
            subdivisions=subs,
        )
        if citation not in found:
            found.append(citation)
    return found


def current_date(title: int, *, client: httpx.Client | None = None) -> str:
    """The date this title was last amended.

    Used as the cache key rather than today's date: keying on today would
    re-download an unchanged regulation every morning, and keying on nothing
    would serve last year's text forever.
    """
    owned = client is None
    client = client or httpx.Client(headers=HEADERS, timeout=60.0)
    try:
        response = client.get(f"{BASE}/titles.json")
        response.raise_for_status()
        for entry in response.json().get("titles", []):
            if entry.get("number") == title:
                date = entry.get("up_to_date_as_of") or entry.get("latest_issue_date")
                if not date:
                    raise CFRError(f"eCFR gave no date for title {title}")
                return str(date)
        raise CFRError(f"eCFR does not publish a title {title}")
    finally:
        if owned:
            client.close()


def fetch_part(title: int, part: str, *, date: str | None = None, log=lambda _: None) -> Path:
    """Download one CFR part as XML, cached on the date it was last amended."""
    date = date or current_date(title)
    dest = CACHE / "cfr" / f"title-{title}-part-{part}-{date}.xml"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"cfr: fetching {title} CFR {part} as of {date}")

    # A whole part is megabytes of XML and eCFR sheds load on it: 503s come
    # back intermittently for the same URL that succeeds moments later. Worth
    # retrying, because the alternative is telling a reviewer a regulation
    # could not be checked when it simply arrived on a busy minute.
    body = b""
    last = ""
    with httpx.Client(headers=HEADERS, timeout=180.0, follow_redirects=True) as client:
        for attempt in range(4):
            if attempt:
                time.sleep(2.0 * attempt)
                log(f"cfr: retrying ({attempt + 1}/4)")
            try:
                response = client.get(
                    f"{BASE}/full/{date}/title-{title}.xml", params={"part": part}
                )
            except httpx.HTTPError as error:
                last = str(error)
                continue
            if response.status_code == 200:
                body = response.content
                break
            last = f"HTTP {response.status_code}: {response.text[:150]}"
            if response.status_code in (400, 404):
                break
    if not body:
        raise CFRError(f"eCFR would not serve {title} CFR {part} -- {last}")

    if b"<DIV" not in body:
        raise CFRError(f"eCFR returned no regulation text for {title} CFR {part}")
    dest.write_bytes(body)
    log(f"cfr: cached {dest.stat().st_size / 1e6:.1f} MB")
    return dest


# --- reading -----------------------------------------------------------------

_MARKER = re.compile(r"^\s*\(([0-9a-zA-Z]{1,4})\)")


@dataclass
class Paragraph:
    path: tuple[str, ...]
    text: str


def _level(marker: str, path: list[str]) -> int:
    """Which nesting level a paragraph marker belongs to.

    CFR nests (a) -> (1) -> (i) -> (A). The only ambiguity is a lone "i", "v"
    or "x", which is both a letter and a roman numeral; it is resolved by
    asking whether it continues the letter run already open -- (h) followed by
    (i) is a letter, (5) followed by (i) is a numeral.
    """
    if marker.isdigit():
        return 1
    if marker.isupper():
        return 3
    roman = re.fullmatch(r"[ivxlc]+", marker) is not None
    if roman and len(marker) > 1:
        return 2
    if not path:
        return 0
    if roman:
        opening = path[0]
        continues_letters = (
            len(opening) == 1 and opening.isalpha() and ord(marker) == ord(opening) + 1
        )
        return 0 if continues_letters else 2
    return 0


def paragraphs(section_node: ET.Element) -> list[Paragraph]:
    """Flatten a section into paragraphs, each tagged with its CFR path."""
    result: list[Paragraph] = []
    path: list[str] = []

    for node in section_node.iter("P"):
        text = " ".join("".join(node.itertext()).split())
        if not text:
            continue
        rest = text
        markers: list[str] = []
        # A paragraph can carry several markers at once: "(5)(i) Non-self-..."
        while (match := _MARKER.match(rest)) and len(markers) < 4:
            markers.append(match.group(1))
            rest = rest[match.end() :]

        for marker in markers:
            level = _level(marker, path)
            path = path[:level]
            path.append(marker)
        result.append(Paragraph(tuple(path), text))
    return result


def section(citation: Citation, *, log=lambda _: None) -> tuple[str, list[Paragraph]]:
    """The heading and paragraphs of one CFR section."""
    path = fetch_part(citation.title, citation.part, log=log)
    root = ET.parse(path).getroot()
    for node in root.iter():
        if node.get("N") == citation.section and node.get("TYPE") == "SECTION":
            head = next(
                (" ".join("".join(h.itertext()).split()) for h in node.iter("HEAD")),
                citation.section,
            )
            return head, paragraphs(node)
    raise CFRError(
        f"{citation.title} CFR {citation.section} does not exist in part {citation.part}"
    )


def find(title: int, part: str, phrase: str, *, log=lambda _: None) -> list[tuple[str, str]]:
    """Every place a phrase appears in a part, as (section, excerpt).

    An empty result is the useful answer as often as a full one -- it is what
    shows that a rule everybody 'knows' is in a standard is not in it.
    """
    path = fetch_part(title, part, log=log)
    root = ET.parse(path).getroot()
    pattern = re.compile(re.escape(phrase), re.IGNORECASE)

    hits: list[tuple[str, str]] = []
    for node in root.iter():
        number = node.get("N") or ""
        if node.get("TYPE") != "SECTION" or not re.fullmatch(r"\d+\.\d+", number):
            continue
        text = " ".join("".join(node.itertext()).split())
        for match in pattern.finditer(text):
            start = max(0, match.start() - 120)
            end = min(len(text), match.end() + 120)
            hits.append((number, ("..." if start else "") + text[start:end].strip() + "..."))
    return hits
