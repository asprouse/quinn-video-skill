# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Generated b-roll via fal.ai, with candidate selection, defect screening
  (undersized frames, letterboxing, safety-filter blanks) and a per-run house
  style so shots read as one shoot.
- `quinn-video verify` — pairs every shot with the words spoken over it, which
  is what catches footage that matches its brief but not its narration.
- `quinn-video candidates` — several draws per shot, chosen by eye.
- `quinn-video probe` — confirms an avatar supports transparent output before
  a full render is paid for.
- Animated 4:1 diagram, and annotation of the rule onto a real photograph.
- Cost guards: `doctor` reports the wallet and what it affords; the avatar
  stage refuses a render the balance cannot cover.
- Installable Claude Code plugin: manifest, marketplace entry, MIT license.
- `short-form-video` skill with craft references for script writing, the
  engagement rubric, visual language, and API notes.
- HeyGen client: narration with word-level timestamps, alpha-WebM avatar
  rendering, render polling, and a readable error when an avatar lacks matting.
- Word-by-word caption layer rendered with Pillow, re-centring as each phrase
  builds, composited as an RGBA overlay.
- Two-pass ffmpeg composition: b-roll base track, then avatar, captions, and
  ducked audio.
- Beat-to-timeline alignment that tolerates TTS retokenising the script.
- Stock sourcing over Pexels and Pixabay that presents candidates for judgement
  rather than picking, with a designed-card fallback.
- `quinn-video grade`: mechanical scoring and a self-contained HTML scorecard.
- Stage-per-subcommand CLI with per-stage caching and a `doctor` preflight.
- pytest suite, ruff config, GitHub Actions CI, and `claude plugin eval` cases.

### Notes
- Captions render via Pillow rather than libass: the default Homebrew ffmpeg
  bottle ships without `libass` and `libfreetype`, and requiring a custom build
  would be a poor trade for a plugin meant to be installed by other people.
