"""Cache artifacts on their inputs, not on their existence.

Every expensive step in this pipeline writes a file and skips the work if that
file is already there. That is right for a crash or a retry and wrong for
everything else, because "the file exists" says nothing about whether it still
matches what produced it.

It has now caused two shipped defects. A re-narrated script kept the previous
avatar, so the presenter lip-synced to words that no longer existed. The same
re-narration kept the previous caption layer, so a finished video showed the
captions of an earlier draft over the audio of a later one. Neither failed.
Both graded clean.

So an artifact records a fingerprint of everything it was built from, and is
rebuilt when that fingerprint changes. The rule for what goes in a
fingerprint: everything that would change the output. When in doubt, include
it — a needless rebuild costs seconds, and a stale artifact ships.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def fingerprint(*parts: Any) -> str:
    """A stable hash of whatever an artifact depends on."""
    blob = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _sidecar(artifact: Path) -> Path:
    return artifact.with_name(artifact.name + ".key")


def is_fresh(artifact: Path, key: str) -> bool:
    """True only if the artifact exists *and* was built from these inputs."""
    if not (artifact.exists() and artifact.stat().st_size > 0):
        return False
    sidecar = _sidecar(artifact)
    if not sidecar.exists():
        # Built before fingerprinting existed, or by hand. Treat as stale:
        # rebuilding is cheap next to shipping something that does not match.
        return False
    return sidecar.read_text(encoding="utf-8").strip() == key


def mark(artifact: Path, key: str) -> None:
    """Record what an artifact was built from."""
    _sidecar(artifact).write_text(key, encoding="utf-8")


def reuse(artifact: Path, key: str, *, force: bool = False) -> bool:
    """Whether to skip rebuilding. `force` always rebuilds."""
    return not force and is_fresh(artifact, key)
