---
name: short-form-video
description: This skill should be used when the user asks for a short-form educational video, an explainer video, a TikTok/Reels/Shorts-style video, safety training video, or asks to "make a video about X". Turns a topic into a finished 30-60 second vertical video with a HeyGen avatar, synced voiceover, word-by-word captions, and on-topic b-roll.
version: 0.1.0
---

# Short-form educational video

Turn a topic into a finished 30–60 second vertical video that teaches one idea
and holds the viewer to the end.

The scripts handle the mechanics. You handle the two things they cannot: writing
a script worth watching, and judging whether a piece of footage actually shows
what the narration describes.

**The bar is engagement, not completeness.** A video that ticks every box and is
boring has failed. Budget most of your effort on the script and the b-roll
choices — that is where videos are won.

## Setup check

Run once per session before anything else:

```bash
uv run quinn-video doctor
```

Fix blockers before continuing. Every paid call is downstream of this.

## The pipeline

Run from the repository root. Each command caches its output, so re-running is
cheap and safe — **except** `narrate` and `avatar`, which cost credits.

### 1. Write the storyboard

```bash
uv run quinn-video init "ladder safety"     # prints the run directory
```

Write `storyboard.json` into that directory. Read
`references/script-craft.md` **before** writing it — the hook rules and pacing
targets there are the difference between a video people watch and one they
swipe past.

Schema: `topic`, `target_seconds`, `hook_variants` (write 3), `chosen_hook`,
`beats[]`. Each beat needs `narration`, `visual.intent`, `visual.queries`, and
optionally `emphasis` and `overlay`.

```bash
uv run quinn-video check     # validates, reports pacing, and lists what will render
```

`check` prints a **render manifest** — every authored overlay and emphasis term,
and a `!` warning for anything that will be silently ignored. Read it. The
common failure is emphasising a numeral: write `"sixty-one"`, not `"161"`,
because the narration says "a hundred and sixty-one" and the accent matches
spoken words.

`check` tells you if the script is too long or short. Fix it now — the word
count is what sets the runtime, and you cannot trim it after paying for audio.

### 2. Grade the hooks before spending anything

Score your three hooks against `references/engagement-rubric.md`. This is free —
it is pure text. Pick the winner, make it beat 1's narration, set `chosen_hook`,
and re-run `check`.

### 3. Narration (costs credits)

```bash
uv run quinn-video narrate
```

Produces the audio and word-level timestamps. Those timestamps drive the
captions, the b-roll cuts, and the avatar lip-sync — one clock for everything.

### 4. B-roll: search, then judge

```bash
uv run quinn-video broll
```

This searches every beat and caches thumbnails. **It picks nothing.** Now do the
part that matters:

1. Read `<run>/broll/candidates.json`.
2. **Look at the thumbnails** with the Read tool. Do not judge from filenames or
   query strings — actually view the images.
3. For each, score 0–3 against that beat's `visual.intent`:
   - **3** — shows exactly the described thing
   - **2** — clearly on-topic and supports the line
   - **1** — same general world, but not the described thing
   - **0** — unrelated
4. Accept the best candidate scoring **≥2**. Prefer video over stills, and
   vertical over landscape (no cropping loss).
5. If nothing scores ≥2, walk the fallback ladder in
   `references/visual-language.md` — ending in a designed card, never a
   loosely-related clip.

Write `<run>/picks.json`:

```json
{
  "1": {"provider": "pexels", "ident": "3196036", "download_url": "..."},
  "2": {"card": true}
}
```

```bash
uv run quinn-video fetch
```

### 5. Avatar and build

```bash
uv run quinn-video avatar    # costs credits; a few minutes
uv run quinn-video build
```

### 6. Grade the result, then fix it

**This step is not optional. The first render is a draft.**

```bash
uv run quinn-video grade
```

This measures what is measurable — duration, speaking rate, dead air, black
frames, clipping, caption-band contrast — and writes `<run>/report.html` with a
frame strip. It exits non-zero on blockers.

It cannot tell you whether the video is *engaging*. So then do the part it
cannot: **view the sampled frames in `<run>/frames/`** and score against
`references/engagement-rubric.md`. Then repair:

- **Visual problems** (wrong shot, caption over a busy area, shot too long) —
  re-pick footage and re-run `build`. Free.
- **Script problems** (weak hook, dead air, rushed explanation) — these need a
  re-`narrate` and re-`avatar`, which costs credits again. Tell the user the
  cost before doing it.

Repeat until the video would genuinely hold someone's attention. Two or three
passes is normal.

## Cost discipline

`narrate` and `avatar` spend money; everything else is free. Get the script
right before step 3, and prefer visual fixes over script fixes afterwards.

## References

- `references/script-craft.md` — hooks, pacing, structure. **Read before writing.**
- `references/engagement-rubric.md` — the grading rubric, used twice.
- `references/visual-language.md` — b-roll judging, the fallback ladder, captions, staging.
- `references/api-notes.md` — HeyGen and Pexels specifics, and the traps.
