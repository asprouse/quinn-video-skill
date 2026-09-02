# Caching

Every expensive step writes a file and skips the work if that file is already
there. That is right for a crash or a retry and wrong for everything else,
because *the file exists* says nothing about whether it still matches what
produced it.

Two defects shipped this way:

- A re-narrated script kept the previous **avatar**, so the presenter
  lip-synced to words that no longer existed and stopped fourteen seconds
  early.
- The same re-narration kept the previous **caption layer**, so a finished
  video showed the captions of an earlier draft over the audio of a later
  one — 25.2s of captions against 39.1s of narration.

Neither failed. Both graded clean. Iterating on a run in place is the normal
way to use this tool, so caching on existence is a defect generator, not an
optimisation.

## The rule

An artifact records a fingerprint of everything it was built from, in a
sidecar `<name>.key` file, and is rebuilt when that fingerprint changes.
`cache.fingerprint()` / `is_fresh()` / `mark()` in `cache.py`.

What goes in a fingerprint: **everything that would change the output**. When
in doubt, include it — a needless rebuild costs seconds, a stale artifact
ships. An artifact with no sidecar is treated as stale.

## What every artifact is keyed on

| Artifact | Keyed on |
|---|---|
| `narration.mp3` | narration text, voice id, speed |
| `avatar.webm` | audio url, avatar id, motion prompt |
| `work/overlay.mov` | word timestamps, emphasis, beat overlays, duration |
| `work/base.mp4` | the cut list: source, start, duration, still, zoom, pan |
| `music.wav` | bed prompt, narration duration |
| `broll/animated-*.mp4` | still, motion prompt, length |
| `broll/annotated-*.mp4` | image, ratio, anchors, duration, cues |
| `broll/diagram-*.mp4` | ratio, duration, cues |

Some artifacts are **content-addressed by filename** instead, which is
equally safe — the name already contains a hash of the inputs, so different
inputs cannot collide on one path:

| Artifact | Addressed by |
|---|---|
| `broll/generated-beat-N-<digest>.jpg` | digest of the image prompt |
| `broll/candidates/*-<digest>-<letter>.jpg` | digest of the image prompt |
| stock downloads, thumbnails | provider + remote id (immutable upstream) |

`broll/card-beat-N.jpg` is redrawn every time; it is local and cheap.

## The safety net

Fingerprints prevent staleness; they do not prove its absence, since a key
can be wrong. So `grade` independently checks that every timed layer —
avatar, captions, b-roll base — runs as long as the narration does. They are
all cut from the same word timestamps, so one disagreeing means it was built
from a different script. That check is a **blocker**.
