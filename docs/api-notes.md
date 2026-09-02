# API notes

Developer reference for the `quinnvideo` package — the shape of the three
services it talks to, and the traps in each.

**This is not part of the skill.** Every constraint below is enforced in code
and commented at its call site; the skill drives the CLI and never touches
these APIs directly. It is here so that someone changing `heygen.py`,
`stock.py` or `compose.py` does not have to rediscover them.

If a failure here ever reaches the skill as something it must reason about,
that is a bad error message and should be fixed as one.

## HeyGen

Base `https://api.heygen.com`, auth header `x-api-key`.

### Narration — `POST /v3/voices/speech`

Returns `audio_url`, `duration`, and **`word_timestamps`** (`[{word, start,
end}]`).

Those timestamps are why narration is generated separately instead of letting
the video endpoint do TTS. They are the single clock for captions, b-roll cuts,
and lip-sync — nothing can drift, because nothing has its own timing.

- Requires a **starfish-engine** voice. Filter with `GET /v3/voices?engine=starfish`.
  A voice outside that engine returns no timestamps and the pipeline refuses to
  continue rather than shipping unsynced captions.
- `speed` 0.5–2.0. Text 1–5000 chars.

### Avatar — `POST /v3/videos`

`type: "avatar"` takes **exactly one** audio source: `script` + `voice_id`,
`audio_url`, or `audio_asset_id`. We always pass `audio_url` — the same audio
the captions are timed against.

- `output_format: "webm"` gives a transparent alpha render.
- **Requires a matting-trained avatar.** No field on the avatar listing
  advertises this; you find out at render time. Newer avatars have it. The
  client raises `MattingUnsupported` with a readable message.
- A `background` parameter is **rejected** alongside webm. Never set one — we
  composite over our own b-roll.
- `aspect_ratio: "9:16"`, `resolution: "1080p"`.
- Send an `Idempotency-Key` so a retry after a network blip does not buy a
  second render.

Poll `GET /v3/videos/{id}` — `pending|processing|completed|failed`. Renders take
minutes. Pay-As-You-Go allows 10 concurrent jobs; 429s carry `Retry-After`.

## Pexels

`https://api.pexels.com`, auth header `Authorization: <key>` (no "Bearer").

- Video: `/videos/search`, photo: `/v1/search`. Both take `orientation`,
  `size`, `per_page` (max 80).
- 200 requests/hour, 20,000/month. Free for commercial use.
- Skip `quality: "hls"` entries in `video_files` — ffmpeg cannot take them as a
  plain file. Prefer the largest progressive file ≤4K.
- Videos carry no caption text, so the thumbnail is the only real evidence of
  what a clip contains. Look at it.

## ffmpeg

### Alpha WebM must be decoded explicitly

```
-c:v libvpx-vp9 -i avatar.webm
```

Without the explicit decoder the native VP9 path **silently drops the alpha
plane** and the avatar composites as an opaque black rectangle. `ffprobe`
reports the stream as `yuv420p` either way — VP9 stores alpha as a separate
WebM stream — so probing is not a useful check. Decode a frame to RGBA and
inspect the alpha channel instead.

### zoompan multiplies

`zoompan=d=N` emits N frames for **every frame it is fed**. Hand it a looped
still and each shot becomes its own length squared — a 15s timeline came out at
378s. Feed stills exactly one frame.

### libass is not available

The default Homebrew ffmpeg bottle ships without `libass` **and** without
`libfreetype`, so neither the `ass`/`subtitles` filter nor `drawtext` works.
Captions are rendered with Pillow into an RGBA layer instead. This is a feature:
the skill runs on any ffmpeg build, and one graphics engine draws captions,
stat cards, and fallback graphics alike.

### Misc

- `-vsync` is removed in ffmpeg 9; use `-fps_mode`.
- Stock footage is nearly always landscape. Scale to cover, then centre-crop to
  1080×1920.
