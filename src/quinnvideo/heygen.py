"""HeyGen API client.

Three things we need from HeyGen, in pipeline order:

1. ``speech()``  -- narration audio *plus* word-level timestamps. Those
   timestamps are the single source of truth for every downstream cut,
   caption, and overlay in the video.
2. ``create_avatar_video()`` -- an alpha-channel WebM of the avatar
   lip-synced to the exact audio from step 1, so nothing can drift.
3. ``wait_for_video()`` -- polling, because renders take minutes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal

import httpx

from .config import require

BASE_URL = "https://api.heygen.com"

# Renders take a few minutes; polling any faster just burns rate limit.
POLL_INTERVAL = 8.0
POLL_TIMEOUT = 900.0


class HeyGenError(RuntimeError):
    """A HeyGen request failed in a way we cannot recover from."""


class MattingUnsupported(HeyGenError):
    """The chosen avatar was not trained with background separation.

    Transparent WebM output requires a matting-trained avatar. Older avatars
    lack it, and the API only tells us at render time -- there is no
    capability flag on the avatar listing to check beforehand.
    """


@dataclass(frozen=True)
class Word:
    """One spoken word and when it lands."""

    word: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Speech:
    audio_url: str
    duration: float
    words: list[Word]

    def to_dict(self) -> dict[str, Any]:
        return {
            "audio_url": self.audio_url,
            "duration": self.duration,
            "words": [{"word": w.word, "start": w.start, "end": w.end} for w in self.words],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Speech:
        return cls(
            audio_url=d["audio_url"],
            duration=d["duration"],
            words=[Word(**w) for w in d["words"]],
        )


class HeyGen:
    def __init__(self, api_key: str | None = None, timeout: float = 60.0) -> None:
        self.api_key = api_key or require("HEYGEN_API_KEY", "avatar rendering and narration")
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"x-api-key": self.api_key, "accept": "application/json"},
            timeout=timeout,
        )

    def __enter__(self) -> HeyGen:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # --- plumbing --------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Issue a request, retrying on 429 and transient 5xx."""
        for attempt in range(5):
            response = self._client.request(method, path, **kwargs)

            if response.status_code == 429:
                # HeyGen tells us exactly how long to wait; honour it.
                delay = float(response.headers.get("Retry-After", 2**attempt))
                time.sleep(min(delay, 60.0))
                continue

            if response.status_code >= 500 and attempt < 4:
                time.sleep(2**attempt)
                continue

            if response.status_code >= 400:
                raise self._error(response)

            return response.json()

        raise HeyGenError(f"{method} {path} still rate-limited after 5 attempts")

    @staticmethod
    def _error(response: httpx.Response) -> HeyGenError:
        try:
            detail = response.json().get("error", {})
            message = detail.get("message") or response.text
            code = detail.get("code", "")
        except ValueError:
            message, code = response.text, ""

        blob = f"{code} {message}".lower()
        if "matting" in blob or "transparent" in blob or "alpha" in blob:
            return MattingUnsupported(
                f"This avatar does not support transparent output: {message}\n"
                "Pick a more recently created avatar "
                "(`quinn-video doctor --list-avatars`), or render opaque."
            )
        return HeyGenError(f"HTTP {response.status_code}: {message}")

    # --- discovery -------------------------------------------------------

    def _paginate(self, path: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        params = {**params, "limit": params.get("limit", 50)}
        while True:
            payload = self._request("GET", path, params=params)
            yield from payload.get("data") or []
            if not payload.get("has_more") or not payload.get("next_token"):
                return
            params["token"] = payload["next_token"]

    def avatars(self, ownership: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if ownership:
            params["ownership"] = ownership
        return list(self._paginate("/v3/avatars/looks", params))

    def voices(self, engine: str = "starfish", **filters: Any) -> list[dict[str, Any]]:
        """List voices. Defaults to the starfish engine, the only one the
        speech endpoint (and therefore word timestamps) accepts."""
        return list(self._paginate("/v3/voices", {"engine": engine, **filters}))

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/v2/user/remaining_quota").get("data", {})

    # --- 1. narration ----------------------------------------------------

    def speech(
        self,
        text: str,
        voice_id: str,
        *,
        speed: float = 1.0,
        locale: str = "en-US",
    ) -> Speech:
        """Synthesise narration and capture its word-level timing.

        The ``word_timestamps`` are the whole reason we generate audio
        separately instead of letting the video endpoint do TTS for us.
        """
        body = {
            "text": text,
            "voice_id": voice_id,
            "input_type": "text",
            "speed": speed,
            "locale": locale,
        }
        data = self._request("POST", "/v3/voices/speech", json=body)["data"]

        timestamps = data.get("word_timestamps")
        if not timestamps:
            raise HeyGenError(
                "HeyGen returned no word_timestamps for this voice. Captions and "
                "b-roll cuts both depend on them. Try a different starfish voice "
                "(`quinn-video doctor --list-voices`)."
            )

        return Speech(
            audio_url=data["audio_url"],
            duration=float(data["duration"]),
            words=[
                Word(word=w["word"], start=float(w["start"]), end=float(w["end"]))
                for w in timestamps
            ],
        )

    # --- 2. avatar -------------------------------------------------------

    def create_avatar_video(
        self,
        avatar_id: str,
        audio_url: str,
        *,
        transparent: bool = True,
        aspect_ratio: str = "9:16",
        resolution: Literal["720p", "1080p", "4k"] = "1080p",
        motion_prompt: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Queue an avatar render lip-synced to our own audio.

        Returns the video id. Note we pass ``audio_url`` rather than a script:
        the avatar must move its mouth to the exact audio our captions are
        timed against.
        """
        body: dict[str, Any] = {
            "type": "avatar",
            "avatar_id": avatar_id,
            "audio_url": audio_url,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": "webm" if transparent else "mp4",
        }
        if motion_prompt:
            body["motion_prompt"] = motion_prompt

        # A `background` key is rejected outright alongside webm, so we never
        # set one -- we composite the avatar over our own b-roll instead.
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._request("POST", "/v3/videos", json=body, headers=headers)["data"]["video_id"]

    # --- 3. polling ------------------------------------------------------

    def get_video(self, video_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v3/videos/{video_id}")["data"]

    def wait_for_video(
        self,
        video_id: str,
        *,
        timeout: float = POLL_TIMEOUT,
        on_poll: Any = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            info = self.get_video(video_id)
            status = info.get("status")

            if on_poll:
                on_poll(status)

            if status == "completed":
                if not info.get("video_url"):
                    raise HeyGenError(f"Video {video_id} completed with no video_url")
                return info

            if status == "failed":
                raise HeyGenError(
                    f"Render failed ({info.get('failure_code')}): {info.get('failure_message')}"
                )

            if time.monotonic() > deadline:
                raise HeyGenError(f"Video {video_id} still '{status}' after {timeout:.0f}s")

            time.sleep(POLL_INTERVAL)


def download(url: str, dest: Path, *, timeout: float = 300.0) -> Path:
    """Stream a remote asset to disk."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_bytes(chunk_size=1 << 16):
                handle.write(chunk)
    return dest
