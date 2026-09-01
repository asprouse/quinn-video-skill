"""Stock footage sourcing.

The brief is blunt about this: "All imagery and background footage is
on-topic. Nothing random or unrelated." Search alone does not get you there
-- query "ladder safety" and stock libraries will happily return a stock
photo of a corporate handshake. So this module returns *candidates* with the
metadata needed to judge them, and the relevance gate upstream decides what
actually makes it into the video.

Pexels is primary. Pixabay is the fallback when Pexels has nothing on-topic,
which happens constantly for specific scenarios like "worker overreaching
sideways off a ladder".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

import httpx

from .config import Keys

Kind = Literal["video", "photo"]


@dataclass
class Candidate:
    """One search hit, with everything the relevance gate needs to judge it."""

    provider: str
    kind: Kind
    ident: str
    download_url: str
    preview_url: str  # thumbnail — what the gate actually looks at
    width: int
    height: int
    duration: float | None
    description: str
    credit: str
    page_url: str

    @property
    def is_vertical(self) -> bool:
        return self.height >= self.width

    def filename(self) -> str:
        suffix = ".mp4" if self.kind == "video" else ".jpg"
        return f"{self.provider}-{self.kind}-{self.ident}{suffix}"


class StockError(RuntimeError):
    pass


# --- Pexels --------------------------------------------------------------


class Pexels:
    BASE = "https://api.pexels.com"

    def __init__(self, api_key: str) -> None:
        self._client = httpx.Client(
            base_url=self.BASE,
            headers={"Authorization": api_key},
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def search(self, query: str, kind: Kind, limit: int = 12) -> list[Candidate]:
        path = "/videos/search" if kind == "video" else "/v1/search"
        response = self._client.get(
            path,
            params={
                "query": query,
                # Ask for portrait first: a vertical source needs no cropping,
                # so nothing important gets cut out of the sides.
                "orientation": "portrait",
                "per_page": limit,
            },
        )
        if response.status_code == 429:
            raise StockError("Pexels rate limit reached (200/hour). Try again shortly.")
        response.raise_for_status()
        payload = response.json()

        if kind == "video":
            return [self._video(v, query) for v in payload.get("videos", [])]
        return [self._photo(p, query) for p in payload.get("photos", [])]

    @staticmethod
    def _video(item: dict[str, Any], query: str) -> Candidate:
        # Prefer the largest progressive file that is not larger than 4K --
        # HLS variants cannot be handed straight to ffmpeg as a file.
        files = [
            f
            for f in item.get("video_files", [])
            if f.get("file_type", "").startswith("video/") and f.get("width")
        ]
        files.sort(key=lambda f: f["width"] or 0, reverse=True)
        best = next((f for f in files if (f["width"] or 0) <= 3840), files[0] if files else None)
        if not best:
            raise StockError(f"Pexels video {item.get('id')} has no downloadable file")

        return Candidate(
            provider="pexels",
            kind="video",
            ident=str(item["id"]),
            download_url=best["link"],
            preview_url=item.get("image", ""),
            width=best.get("width") or item.get("width", 0),
            height=best.get("height") or item.get("height", 0),
            duration=float(item.get("duration") or 0) or None,
            # Pexels videos carry no caption, so the query is the only textual
            # hint. The gate looks at the thumbnail regardless.
            description=query,
            credit=(item.get("user") or {}).get("name", "Pexels"),
            page_url=item.get("url", ""),
        )

    @staticmethod
    def _photo(item: dict[str, Any], query: str) -> Candidate:
        src = item.get("src", {})
        return Candidate(
            provider="pexels",
            kind="photo",
            ident=str(item["id"]),
            download_url=src.get("original") or src.get("large2x") or src.get("large", ""),
            preview_url=src.get("medium") or src.get("small", ""),
            width=item.get("width", 0),
            height=item.get("height", 0),
            duration=None,
            description=item.get("alt") or query,
            credit=item.get("photographer", "Pexels"),
            page_url=item.get("url", ""),
        )


# --- Pixabay -------------------------------------------------------------


class Pixabay:
    BASE = "https://pixabay.com/api"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._client = httpx.Client(base_url=self.BASE, timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def search(self, query: str, kind: Kind, limit: int = 12) -> list[Candidate]:
        path = "/videos/" if kind == "video" else "/"
        params = {"key": self.api_key, "q": query, "per_page": max(3, limit), "safesearch": "true"}
        if kind == "photo":
            params["image_type"] = "photo"

        response = self._client.get(path, params=params)
        if response.status_code == 429:
            raise StockError("Pixabay rate limit reached (100/min).")
        response.raise_for_status()
        hits = response.json().get("hits", [])

        return [
            self._video(h) if kind == "video" else self._photo(h)
            for h in hits
        ]

    @staticmethod
    def _video(item: dict[str, Any]) -> Candidate:
        streams = item.get("videos", {})
        best = streams.get("large") or streams.get("medium") or streams.get("small") or {}
        return Candidate(
            provider="pixabay",
            kind="video",
            ident=str(item["id"]),
            download_url=best.get("url", ""),
            preview_url=f"https://i.vimeocdn.com/video/{item.get('picture_id')}_295x166.jpg"
            if item.get("picture_id")
            else "",
            width=best.get("width", 0),
            height=best.get("height", 0),
            duration=float(item.get("duration") or 0) or None,
            description=item.get("tags", ""),
            credit=item.get("user", "Pixabay"),
            page_url=item.get("pageURL", ""),
        )

    @staticmethod
    def _photo(item: dict[str, Any]) -> Candidate:
        return Candidate(
            provider="pixabay",
            kind="photo",
            ident=str(item["id"]),
            download_url=item.get("largeImageURL") or item.get("webformatURL", ""),
            preview_url=item.get("previewURL", ""),
            width=item.get("imageWidth", 0),
            height=item.get("imageHeight", 0),
            duration=None,
            description=item.get("tags", ""),
            credit=item.get("user", "Pixabay"),
            page_url=item.get("pageURL", ""),
        )


# --- facade --------------------------------------------------------------


class Stock:
    """Search every configured provider, best source first."""

    def __init__(self, keys: Keys | None = None) -> None:
        keys = keys or Keys.load()
        if not keys.pexels:
            raise StockError("PEXELS_API_KEY is not set. Needed for b-roll. See .env.example.")
        self.pexels = Pexels(keys.pexels)
        self.pixabay = Pixabay(keys.pixabay) if keys.pixabay else None

    def close(self) -> None:
        self.pexels.close()
        if self.pixabay:
            self.pixabay.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def search(
        self,
        query: str,
        kind: Kind = "video",
        *,
        limit: int = 12,
        include_fallback: bool = True,
    ) -> list[Candidate]:
        results = self.pexels.search(query, kind, limit)
        if include_fallback and self.pixabay and len(results) < 4:
            results += self.pixabay.search(query, kind, limit)
        return results

    @staticmethod
    def fetch(candidate: Candidate, cache_dir: Path) -> Path:
        """Download a candidate, reusing the cached copy when we already have it."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        dest = cache_dir / candidate.filename()
        if dest.exists() and dest.stat().st_size > 0:
            return dest

        with httpx.stream(
            "GET", candidate.download_url, timeout=180.0, follow_redirects=True
        ) as response:
            response.raise_for_status()
            partial = dest.with_suffix(dest.suffix + ".part")
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size=1 << 16):
                    handle.write(chunk)
            partial.replace(dest)
        return dest
