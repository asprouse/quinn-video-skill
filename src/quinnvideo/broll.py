"""Sourcing on-topic footage.

The brief's hardest requirement is negative: "Nothing random or unrelated."
Stock search cannot deliver that on its own -- searching "ladder safety"
returns handshakes and generic office footage alongside the real thing.

So the split here is deliberate. This module *finds and presents* candidates
with their thumbnails; judging them is Claude's job, because judging whether
a picture shows what a sentence describes is exactly the kind of thing a
search API cannot do and a model can. What comes back is a decision, not a
ranking, and if nothing clears the bar the fallback ladder ends in a designed
card rather than a shrug.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from . import graphics
from .runs import Run
from .stock import Candidate, Stock
from .storyboard import Beat, Storyboard

Log = Callable[[str], None]


def _noop(_: str) -> None:
    return None


def gather(
    run: Run,
    board: Storyboard,
    *,
    per_query: int = 8,
    log: Log = _noop,
) -> dict[str, Any]:
    """Search every beat's queries and cache the thumbnails for inspection.

    Writes ``candidates.json`` and a thumbnail per candidate. Nothing is
    downloaded at full size yet -- that happens only for what gets picked.
    """
    thumbs = run.broll_dir / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {"beats": []}

    with Stock() as stock:
        for beat in board.beats:
            found: list[Candidate] = []
            seen: set[str] = set()

            for query in beat.visual.queries:
                try:
                    hits = stock.search(query, beat.visual.prefer, limit=per_query)
                except Exception as exc:
                    log(f"beat {beat.id}: search '{query}' failed — {exc}")
                    continue

                for hit in hits:
                    key = f"{hit.provider}:{hit.ident}"
                    if key not in seen:
                        seen.add(key)
                        found.append(hit)

            # If a beat wanted video and got almost nothing, try stills before
            # giving up -- a strong photograph with a Ken Burns move beats a
            # weak video every time.
            if len(found) < 3 and beat.visual.prefer == "video":
                for query in beat.visual.queries[:2]:
                    try:
                        for hit in stock.search(query, "photo", limit=per_query):
                            key = f"{hit.provider}:{hit.ident}"
                            if key not in seen:
                                seen.add(key)
                                found.append(hit)
                    except Exception as exc:
                        log(f"beat {beat.id}: photo search failed — {exc}")

            entries = []
            for candidate in found:
                thumb = _cache_thumb(candidate, thumbs)
                entries.append(
                    {
                        **asdict(candidate),
                        "thumbnail": str(thumb) if thumb else None,
                        "vertical": candidate.is_vertical,
                    }
                )

            log(f"beat {beat.id}: {len(entries)} candidates for '{beat.visual.intent}'")
            manifest["beats"].append(
                {
                    "id": beat.id,
                    "narration": beat.narration,
                    "intent": beat.visual.intent,
                    "queries": beat.visual.queries,
                    "candidates": entries,
                }
            )

    path = run.broll_dir / "candidates.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _cache_thumb(candidate: Candidate, directory: Path) -> Path | None:
    if not candidate.preview_url:
        return None
    dest = directory / f"{candidate.provider}-{candidate.ident}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        response = httpx.get(candidate.preview_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        dest.write_bytes(response.content)
        return dest
    except Exception:
        return None


def fetch_picks(
    run: Run, picks: dict[int, list[dict[str, str]]], *, log: Log = _noop
) -> dict[int, list[Path]]:
    """Download the full-size asset for every accepted candidate.

    ``picks`` maps a beat id to a list of ``{"provider":..., "ident":...}``
    entries chosen from the candidate manifest. Several per beat is normal:
    long beats need more than one shot to stay alive.
    """
    manifest = json.loads((run.broll_dir / "candidates.json").read_text(encoding="utf-8"))
    # Keyed globally, not per beat. The same clip often surfaces under several
    # beats' searches, and a reviewer who spots the right shot while reviewing
    # one beat should be able to use it on any of them.
    lookup = {
        (c["provider"], c["ident"]): c for b in manifest["beats"] for c in b["candidates"]
    }

    resolved: dict[int, list[Path]] = {}
    with Stock() as stock:
        for beat_id, chosen in picks.items():
            for pick in chosen:
                entry = lookup.get((pick["provider"], pick["ident"]))
                if not entry:
                    log(f"beat {beat_id}: {pick} is in no beat's candidate list")
                    continue
                candidate = Candidate(
                    **{k: v for k, v in entry.items() if k not in ("thumbnail", "vertical")}
                )
                resolved.setdefault(int(beat_id), []).append(
                    stock.fetch(candidate, run.broll_dir)
                )
                log(f"beat {beat_id}: {candidate.filename()}")

    return resolved


def fallback_card(run: Run, beat: Beat, *, log: Log = _noop) -> Path:
    """Draw a designed card for a beat with no acceptable footage."""
    dest = run.broll_dir / f"card-beat-{beat.id}.jpg"
    # The overlay text is authored for the screen; the headline falls back to
    # the narration. visual.intent is a search instruction and must never
    # appear -- it reads as debug output leaking into the video.
    text = beat.overlay.text if beat.overlay else _headline(beat)
    kicker = "the rule" if beat.overlay and beat.overlay.kind == "rule" else ""
    graphics.render_card(text, dest, kicker=kicker)
    log(f"beat {beat.id}: no footage cleared the bar — designed card instead")
    return dest


def _headline(beat: Beat) -> str:
    """Pull a short headline out of the narration for a fallback card."""
    if beat.emphasis:
        return " ".join(beat.emphasis[:4])
    words = beat.narration.replace(",", "").split()
    return " ".join(words[:6])
