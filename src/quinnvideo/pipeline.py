"""Stage orchestration.

Each function here is one resumable step. They are deliberately separate and
individually invocable: the two that cost money (narration, avatar) must
never re-run because something cheap downstream broke, and the grading loop
rebuilds only the visual stages.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from . import captions, compose, ff
from .align import BeatTiming, align, normalise
from .compose import Composition, Segment
from .config import MAX_SHOT, SLOW_WPM, VOICE_SPEED, require
from .heygen import HeyGen, HeyGenError, Speech, download, estimate_cost
from .runs import Run
from .storyboard import Storyboard

Log = Callable[[str], None]


def _noop(_: str) -> None:
    return None


# --- stage 1: narration --------------------------------------------------


def narrate(
    run: Run,
    board: Storyboard,
    *,
    voice_id: str | None = None,
    speed: float | None = None,
    force: bool = False,
    log: Log = _noop,
) -> Speech:
    """Synthesise the voiceover and capture its word-level timing.

    Costs credits, so it is cached hard: the audio file and the timestamps are
    both reused unless explicitly forced.
    """
    voice_id = voice_id or require("QUINN_VOICE_ID", "narration")
    speed = VOICE_SPEED if speed is None else speed

    if run.speech_path.exists() and run.has(run.audio) and not force:
        log("narration: cached")
        return Speech.from_dict(json.loads(run.speech_path.read_text(encoding="utf-8")))

    log(f"narration: synthesising {board.word_count} words")
    with HeyGen() as client:
        speech = client.speech(board.narration, voice_id, speed=speed)

    run.speech_path.write_text(json.dumps(speech.to_dict(), indent=2), encoding="utf-8")
    download(speech.audio_url, run.audio)
    rate = len(speech.words) / speech.duration * 60 if speech.duration else 0
    log(f"narration: {speech.duration:.1f}s, {len(speech.words)} words, {rate:.0f} wpm")
    if rate < SLOW_WPM:
        log(
            f"narration: {rate:.0f} wpm is slow for short-form — it will feel "
            f"lethargic. Raise QUINN_VOICE_SPEED (now {speed}) and re-run "
            "`narrate --force`; it costs about three cents and must happen "
            "before the avatar render."
        )
    return speech


# --- stage 2: avatar -----------------------------------------------------


def submit_avatar(
    run: Run,
    speech: Speech,
    *,
    avatar_id: str | None = None,
    transparent: bool = True,
    engine: str = "avatar_iv",
    log: Log = _noop,
) -> str:
    """Queue the avatar render and return without waiting.

    The render takes minutes of pure waiting, and choosing b-roll takes
    minutes of work that does not depend on it. Running them at the same time
    is most of the wall-clock difference in a full build.
    """
    existing = run.state().get("avatar_video_id")
    if existing and not run.has(run.avatar):
        log(f"avatar: already queued as {existing}")
        return existing

    avatar_id = avatar_id or require("QUINN_AVATAR_ID", "the presenter")
    with HeyGen() as client:
        cost = estimate_cost(speech.duration, engine)
        balance = client.balance()
        if balance is not None:
            log(f"avatar: ~${cost:.2f} for {speech.duration:.0f}s, ${balance:.2f} available")
            if balance < cost:
                raise HeyGenError(
                    f"insufficient balance: this render costs about ${cost:.2f} and the "
                    f"wallet holds ${balance:.2f}. Shorten the script or top up."
                )
        video_id = client.create_avatar_video(
            avatar_id,
            speech.audio_url,
            transparent=transparent,
            idempotency_key=f"{run.directory.name}-avatar",
        )
    run.update_state(avatar_video_id=video_id)
    log(f"avatar: queued {video_id} — carry on with b-roll while it renders")
    return video_id


def collect_avatar(run: Run, *, log: Log = _noop) -> Path:
    """Wait for a queued render and download it."""
    if run.has(run.avatar):
        log("avatar: cached")
        return run.avatar

    video_id = run.state().get("avatar_video_id")
    if not video_id:
        raise HeyGenError("no avatar render has been queued for this run")

    with HeyGen() as client:
        seen: set[str] = set()

        def note(status: str) -> None:
            if status not in seen:
                seen.add(status)
                log(f"avatar: {status}")

        info = client.wait_for_video(video_id, on_poll=note)

    download(info["video_url"], run.avatar)
    log(f"avatar: downloaded ({run.avatar.stat().st_size / 1e6:.1f} MB)")
    return run.avatar


def render_avatar(
    run: Run,
    speech: Speech,
    *,
    avatar_id: str | None = None,
    transparent: bool = True,
    engine: str = "avatar_iv",
    force: bool = False,
    log: Log = _noop,
) -> Path:
    """Render the presenter, lip-synced to the narration we already have."""
    avatar_id = avatar_id or require("QUINN_AVATAR_ID", "the presenter")

    if run.has(run.avatar) and not force:
        log("avatar: cached")
        return run.avatar

    log("avatar: queuing render")
    with HeyGen() as client:
        # The single most expensive call in the pipeline. Check first: running
        # dry mid-render wastes the narration we have already paid for.
        cost = estimate_cost(speech.duration, engine)
        balance = client.balance()
        if balance is not None:
            log(f"avatar: ~${cost:.2f} for {speech.duration:.0f}s, ${balance:.2f} available")
            if balance < cost:
                raise HeyGenError(
                    f"insufficient balance: this render costs about ${cost:.2f} and the "
                    f"wallet holds ${balance:.2f}. Shorten the script or top up."
                )
        video_id = client.create_avatar_video(
            avatar_id,
            speech.audio_url,
            transparent=transparent,
            # A run only ever needs one avatar, so keying on the run name makes
            # a retry after a network blip reuse the render instead of buying
            # a second one.
            idempotency_key=f"{run.directory.name}-avatar",
        )
        run.update_state(avatar_video_id=video_id)
        log(f"avatar: {video_id}, waiting")

        seen: set[str] = set()

        def note(status: str) -> None:
            if status not in seen:
                seen.add(status)
                log(f"avatar: {status}")

        info = client.wait_for_video(video_id, on_poll=note)

    download(info["video_url"], run.avatar)
    log(f"avatar: downloaded ({run.avatar.stat().st_size / 1e6:.1f} MB)")
    return run.avatar


# --- stage 3: caption and graphics layer ---------------------------------


def render_overlay(
    run: Run,
    speech: Speech,
    timings: list[BeatTiming] | None = None,
    *,
    force: bool = False,
    log: Log = _noop,
) -> Path:
    """Draw captions and beat overlays. Free, so it rebuilds on any change."""
    if run.has(run.overlay) and not force:
        log("overlay: cached")
        return run.overlay

    cues: list[captions.OverlayCue] = []
    emphasis: list[tuple[float, float, set[str]]] = []

    # Beats whose footage *is* their graphic -- a designed card or a generated
    # diagram. Their overlay text is already the artwork, so drawing it again
    # as an overlay prints the same words twice on the same shot.
    is_artwork = set(run.state().get("generated") or [])

    for timing in timings or []:
        beat = timing.beat
        if (
            beat.overlay
            and beat.overlay.kind in ("stat", "label", "rule")
            and beat.id not in is_artwork
        ):
            cues.append(
                captions.OverlayCue(
                    start=timing.start + 0.15,
                    end=timing.end,
                    text=beat.overlay.text,
                    kind=beat.overlay.kind,
                )
            )
        if beat.emphasis:
            emphasis.append(
                (timing.start, timing.end, {normalise(w) for w in _split(beat.emphasis)})
            )

    def emphasised(word) -> bool:
        """Scoped to the beat that authored it, so a common word like "one"
        is not accented everywhere it happens to occur."""
        token = normalise(word.word)
        return any(start <= word.start < end and token in terms for start, end, terms in emphasis)

    log(
        "overlay: captions"
        + (f", {len(cues)} beat overlay(s)" if cues else "")
        + (f", emphasis on {len(emphasis)} beat(s)" if emphasis else "")
    )
    captions.render_layer(
        speech.words,
        run.overlay,
        duration=speech.duration,
        emphasised=emphasised if emphasis else None,
        cues=cues,
    )
    log(f"overlay: {run.overlay.stat().st_size / 1e6:.1f} MB")
    return run.overlay


def _split(phrases: list[str]) -> list[str]:
    """Emphasis may be authored as phrases ("ten feet"); accent each word."""
    return [word for phrase in phrases for word in phrase.split()]


# --- stage 4: composition ------------------------------------------------


def plan_segments(
    timings: list[BeatTiming],
    picks: dict[int, list[Path]],
    *,
    max_shot: float = MAX_SHOT,
    atomic: set[int] | None = None,
    log: Log = _noop,
) -> list[Segment]:
    """Turn beat timings plus chosen footage into a cut list.

    A beat that outlasts ``max_shot`` is cut into several shots.

    The cap used to be four seconds, which on a fifty-second video forced
    fourteen shots -- fourteen things to source, judge and pay for. Most of
    that was a workaround for stills sitting dead on screen, and the Ken Burns
    move now scales with the hold, so a longer shot still moves. Seven seconds
    roughly halves the asset count for the same finished video.

    A beat may carry more than one clip, and the cuts rotate through them.
    That matters because the long beats are the ones most in need of variety:
    holding a single clip for nine seconds reads as a stall no matter how
    well it matches the narration.
    """
    segments: list[Segment] = []

    for timing in timings:
        sources = picks.get(timing.beat.id) or []
        if not sources:
            log(f"beat {timing.beat.id}: no footage, skipped")
            continue

        span = max(0.4, timing.duration)
        if atomic and timing.beat.id in atomic:
            # A generated animation plays once, start to finish. Splitting it
            # into equal shots would restart it partway through.
            shots = 1
        else:
            # Never fewer shots than we have clips for this beat -- a second
            # clip the reviewer chose should always make it on screen.
            shots = max(len(sources), 1, round(span / max_shot + 0.35))
        each = span / shots

        for n in range(shots):
            source = sources[n % len(sources)]
            segments.append(
                Segment(
                    source=source,
                    start=timing.start + n * each,
                    duration=each,
                    is_still=source.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"},
                    # Alternate the Ken Burns direction so repeated shots of
                    # one still do not read as a loop.
                    zoom_in=(len(segments) % 2 == 0),
                    pan=("right", "left")[len(segments) % 2],
                )
            )

    return segments


def _cut_fingerprint(segments: list[Segment]) -> str:
    """Identifies a cut list: which clip plays, for how long, in what order."""
    import hashlib

    joined = "|".join(
        f"{seg.source}:{seg.start:.3f}:{seg.duration:.3f}:{seg.is_still}:{seg.zoom_in}"
        for seg in segments
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _segment_beats(segments: list[Segment], picks_index: dict[str, int]) -> list[int]:
    """Which beat each shot came from, looked up by its source file."""
    return [picks_index.get(str(seg.source), 0) for seg in segments]


def build(
    run: Run,
    speech: Speech,
    segments: list[Segment],
    *,
    picks_index: dict[str, int] | None = None,
    music: Path | None = None,
    force: bool = False,
    log: Log = _noop,
) -> Path:
    """Composite everything into the finished video."""
    picks_index = picks_index or {}
    comp = Composition(
        segments=segments,
        narration=run.audio,
        duration=speech.duration,
        avatar=run.avatar if run.has(run.avatar) else None,
        overlay=run.overlay if run.has(run.overlay) else None,
        music=music,
    )

    log(compose.describe(comp))

    # The cut list is what `verify` reads back to pair each shot with the
    # words spoken over it. It is not recoverable from the finished mp4.
    run.update_state(
        segments=[
            {
                "start": round(seg.start, 3),
                "duration": round(seg.duration, 3),
                "source": str(seg.source),
                "beat": beat_id,
            }
            for seg, beat_id in zip(segments, _segment_beats(segments, picks_index), strict=True)
        ]
    )

    # Keyed on the cut list, not merely on the file existing. Caching by
    # existence meant swapping a shot rebuilt nothing: the finished video
    # silently kept the old footage and only --force fixed it, which is a
    # trap nobody should have to know about.
    fingerprint = _cut_fingerprint(comp.segments)
    stamp = run.base.with_suffix(".cut")
    stale = not stamp.exists() or stamp.read_text(encoding="utf-8") != fingerprint

    if not run.has(run.base) or stale or force:
        log("compose: building b-roll base" + (" (cut list changed)" if stale else ""))
        compose.build_base(comp, run.base)
        stamp.write_text(fingerprint, encoding="utf-8")

    log("compose: laying avatar, captions, audio")
    compose.build_final(comp, run.base, run.final)

    # Record where the presenter ended up. The grader needs the geometry to
    # tell whether it is sitting on top of the captions, and that is not
    # recoverable from the finished mp4.
    run.update_state(
        staging=[
            {
                "start": st.start,
                "end": st.end,
                "scale": st.scale,
                "anchor": st.anchor,
                "rect": compose.stage_rect(st, comp.avatar),
            }
            for st in (comp.stages or compose.default_stages(comp.duration))
        ]
        if comp.avatar
        else []
    )

    info = ff.probe(run.final)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    log(
        f"done: {run.final} — {stream['width']}x{stream['height']}, "
        f"{float(info['format']['duration']):.1f}s, "
        f"{int(info['format']['size']) / 1e6:.1f} MB"
    )
    return run.final


# --- convenience ---------------------------------------------------------


def timings_for(board: Storyboard, speech: Speech, *, log: Log = _noop) -> list[BeatTiming]:
    timings = align(board, speech.words)
    estimated = [t for t in timings if not t.aligned]
    if estimated:
        log(
            f"align: {len(estimated)} of {len(timings)} beats estimated rather than matched "
            "— check the script against the narration"
        )
    return timings
