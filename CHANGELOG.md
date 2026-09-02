# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **A claims ledger on the storyboard.** Nothing in this pipeline checked
  whether a script was *true* — every mechanical check was about duration,
  sync or footage, and the script was taken on trust. Every factual assertion
  now goes in `claims[]` with a status and a source, `check` blocks on a beat
  that asserts something the ledger does not mention (numbers spelled out or
  in digits, ratios, named standards, universals — in overlay text as well as
  narration), and the ledger prints at the approval gate ahead of the cost.
  It does not verify anything; it makes assertions visible to the person who
  can. See `docs/claims.md`.

- **`quinn-video sources`** — lists the numeric claims that still lack a
  primary source, for checking with a domain-restricted search, and `check`
  now blocks a claim marked `established` on a secondary one. Open web search
  is not an independent check of a model trained on the web; the value is
  entirely in reaching a primary source, so the rule is about where an answer
  came from rather than whether one was found. See `docs/claims.md`.

### Fixed
- **Artifacts are cached on their inputs, not their existence.** Every
  expensive stage skipped its work whenever its output file was present,
  which is right for a retry and wrong for iterating on a run in place. Two
  defects shipped this way: a re-narrated script kept the previous avatar
  (lip-synced to words that no longer existed), and kept the previous caption
  layer (25.2s of captions over 39.1s of narration). Narration, avatar,
  captions, b-roll base, music, animated shots, diagrams and annotations now
  each record a fingerprint of what they were built from and rebuild when it
  changes. See `docs/caching.md`.
- **`grade` blocks on any timed layer that disagrees with the narration.**
  The avatar, captions and b-roll base are all cut from the same word
  timestamps, so one running to a different length means it was built from a
  different script. Previously only the avatar was checked, and the stale
  caption layer graded clean.
- **The music bed no longer sits in the voice band.** One generated bed came
  back with 38% of its energy in 2–6 kHz — the band carrying speech
  intelligibility and sibilance — and read as hiss fighting the narrator.
  Beds are now high-passed, scooped through the presence band, low-passed and
  normalised to an absolute level rather than scaled by a fixed gain, since
  generated beds arrive slammed to 0 dBFS with unpredictable spectral
  balance. `generate_bed` warns when a bed crowds the voice band, and the
  prompt it was made from is kept beside it.

### Removed
- `Run.cached()`, which had no callers and cached on existence.

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
- `video` skill (invoked as `/quinn:video`) with craft references for script writing, the
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
