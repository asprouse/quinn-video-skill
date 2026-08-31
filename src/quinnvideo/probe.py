"""Cheap capability probe for transparent avatar rendering.

Transparent WebM requires a matting-trained avatar. HeyGen exposes no flag for
this on the avatar listing -- you find out at render time -- and the whole
compositing design depends on the answer. So: render five seconds and look at
the alpha channel, for a fraction of the cost of discovering it on a full one.

Worth running once per avatar before committing to it.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import ff
from .heygen import HeyGen, HeyGenError, MattingUnsupported, download, estimate_cost

# Just long enough to get a real render back. Billing is per second, so this
# is the smallest useful question we can ask.
PROBE_SECONDS = 5
PROBE_LINE = "Check the angle of your ladder before you climb it."


@dataclass
class ProbeResult:
    avatar_id: str
    engine: str
    transparent: bool
    detail: str
    width: int = 0
    height: int = 0
    cost: float = 0.0


def probe_transparency(
    avatar_id: str,
    voice_id: str,
    *,
    engine: str = "avatar_iii",
    keep: Path | None = None,
    log=lambda _: None,
) -> ProbeResult:
    cost = estimate_cost(PROBE_SECONDS, engine)
    log(f"probe: {avatar_id} on {engine}, ~${cost:.2f}")

    with HeyGen() as client:
        balance = client.balance()
        if balance is not None and balance < cost:
            raise HeyGenError(f"balance ${balance:.2f} will not cover a ${cost:.2f} probe")

        speech = client.speech(PROBE_LINE, voice_id)
        log(f"probe: narration {speech.duration:.1f}s")

        try:
            video_id = client.create_avatar_video(
                avatar_id,
                speech.audio_url,
                transparent=True,
                engine=engine,
                idempotency_key=f"probe-{avatar_id}-{engine}",
            )
        except MattingUnsupported as exc:
            # Rejected before rendering, which is the cheapest possible answer.
            return ProbeResult(avatar_id, engine, False, str(exc).splitlines()[0], cost=0.0)

        log(f"probe: {video_id}, waiting")
        try:
            info = client.wait_for_video(video_id, on_poll=lambda s: log(f"probe: {s}"))
        except MattingUnsupported as exc:
            return ProbeResult(avatar_id, engine, False, str(exc).splitlines()[0], cost=cost)

    dest = keep or Path(tempfile.mkdtemp()) / "probe.webm"
    download(info["video_url"], dest)
    log(f"probe: downloaded {dest} ({dest.stat().st_size / 1e6:.1f} MB)")

    transparent, detail = _has_alpha(dest)
    stream = ff.video_stream(dest)
    return ProbeResult(
        avatar_id=avatar_id,
        engine=engine,
        transparent=transparent,
        detail=detail,
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        cost=cost,
    )


def _has_alpha(video: Path) -> tuple[bool, str]:
    """Decode a frame and inspect the alpha channel.

    ffprobe is no help here: VP9 stores alpha as a separate WebM stream and
    reports the primary plane as yuv420p either way. The only reliable test is
    to decode with libvpx-vp9 and look at the pixels.
    """
    from PIL import Image

    frame = video.parent / "probe-frame.png"
    ff.run(
        ["-c:v", "libvpx-vp9", "-i", str(video), "-frames:v", "1", "-ss", "1",
         "-pix_fmt", "rgba", str(frame)]
    )

    image = Image.open(frame).convert("RGBA")
    alpha = image.split()[3]
    low, high = alpha.getextrema()

    if low == high == 255:
        return False, "fully opaque — this avatar renders with a baked background"
    if high == 0:
        return False, "fully transparent — the render appears empty"

    transparent_px = sum(1 for value in alpha.getdata() if value < 16)
    share = transparent_px / (image.width * image.height)
    return True, f"alpha present — {share:.0%} of the frame is transparent"
