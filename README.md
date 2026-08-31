# quinn-video

A Claude Code skill that turns a topic into a finished 30–60 second vertical
educational video — the kind of short-form explainer that actually holds a
viewer to the end.

Give it `ladder safety` and it returns an mp4 with a HeyGen avatar presenting,
a voiceover, word-by-word captions locked to the narration, and a fast-cut
slideshow of on-topic footage.

> Status: in development. See [CHANGELOG.md](CHANGELOG.md).

## Install

```
/plugin marketplace add asprouse/quinn-video-skill
/plugin install quinn-video
```

## Setup

```
cp .env.example .env    # add HEYGEN_API_KEY and PEXELS_API_KEY
uv run quinn-video doctor
```

`doctor` checks the toolchain and credentials before anything spends credits.
Use `--list-avatars` and `--list-voices` to pick your presenter.

## Requirements

- `ffmpeg` with VP9 decode and libx264 (the default Homebrew bottle is fine)
- `uv`
- A HeyGen account and a free Pexels API key

## License

MIT
