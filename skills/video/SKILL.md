---
name: video
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

**Work down this file in order, and do not read ahead.** Three reference files
sit alongside it. Each is named at the one step that needs it, and should be
read *at* that step, not before. Reading all three up front costs more than
this whole file and is wasted on any run that stops early — most do, at the
credentials check two paragraphs below.

## Setup

Do this first, once per session. Every command below runs through the plugin's
own checkout while leaving the working directory alone, so runs, footage and
`.env` all land beside the **user's** project rather than inside the plugin:

```bash
export QV="uv run --project ${CLAUDE_PLUGIN_ROOT} quinn-video"
$QV doctor
```

`doctor` checks ffmpeg, the typefaces, the credentials, and the HeyGen balance.

**If it reports blockers, stop here and say so. Do not write a storyboard.**
Report the blockers, the exact fix, and nothing else. `init` will refuse
anyway, but the point is to tell the user in ten seconds rather than after
two minutes of work they did not ask for and may not be able to use.

Writing the script first is tempting because it is free — but free is not the
same as costless. It spends the user's attention on a plan they cannot run,
and buries the one thing blocking them under a wall of text. Ask whether they
want a draft while they find the keys; do not assume it. If they say yes,
`init --draft` skips the check.

Every other command also preflights what *it* needs and refuses to start
otherwise, so a missing key stops the run immediately rather than several
stages in. If one refuses, it names the fix.

If credentials are missing, the user needs a `.env` **in their working
directory** (not in the plugin):

```bash
cp "${CLAUDE_PLUGIN_ROOT}/.env.example" .env    # then fill in the keys
$QV fonts                                        # one-off, downloads the typefaces
```

## The pipeline

Each command caches its output, so re-running is cheap and safe — **except**
`narrate` and `avatar`, which cost credits.

### 1. Write the storyboard

```bash
$QV init "ladder safety"     # prints the run directory
```

Write `storyboard.json` into that directory. Read
`references/script-craft.md` **now, before writing** — the hook rules and pacing
targets there are the difference between a video people watch and one they
swipe past.

Schema: `topic`, `target_seconds`, `hook_variants` (write 3), `chosen_hook`,
`beats[]`, `claims[]`. Each beat needs `narration`, `visual.intent`,
`visual.queries`, and optionally `visual.prompt`, `emphasis` and `overlay`.

`visual.prompt` is where a generation prompt belongs — not `picks.json`, which
is a record of one run's choices. A prompt kept only there is lost the moment
the storyboard is rebuilt.

```bash
$QV check     # validates, reports pacing, and lists what will render
```

`check` prints a **render manifest** — every authored overlay and emphasis term,
and a `!` warning for anything that will be silently ignored. Read it. The
common failure is emphasising a numeral: write `"sixty-one"`, not `"161"`,
because the narration says "a hundred and sixty-one" and the accent matches
spoken words.

`check` tells you if the script is too long or short. Fix it now — the word
count is what sets the runtime, and you cannot trim it after paying for audio.

**`check` also blocks on any assertion missing from the claims ledger.** Write
`claims[]` as you write the script, not afterwards — see *Claims* below.

### 1b. The claims ledger

Nothing in this pipeline checks whether the script is **true**. Every other
check is mechanical: duration, sync, black frames, whether footage matches the
beat. A wrong number in a safety video is worse than a dull one, so every
factual assertion goes in `claims[]` with where it came from:

```json
{ "beat": 2,
  "text": "A load at arm's length puts roughly ten times its weight through the lower back",
  "status": "estimate",
  "source": "Lever-arm biomechanics; the NIOSH lifting equation treats horizontal distance as a primary multiplier.",
  "note": "~10x is the standard teaching figure. The real multiplier varies with posture and build, which is why the line says 'roughly'." }
```

`status` is the honest one, not the flattering one:

| status | means |
|---|---|
| `established` | documented in a standard, regulation or published dataset — **requires a `source`** |
| `contested` | real, but disputed or a simplification of a contested picture |
| `estimate` | a rule of thumb; **the narration must hedge it** ("roughly", "about") |
| `unverified` | from your recall, not confirmed against a source |
| `illustrative` | arithmetic derived from another claim, or a procedural instruction |

Rules:

- **`unverified` is a legitimate answer.** It is what you should use whenever
  you are working from recall, which is most of the time. Marking a recalled
  figure `established` to make the check pass is the single worst thing you
  can do here — it converts "nobody has checked this" into "this is
  documented", which is exactly the false confidence the ledger exists to
  prevent.
- Do not invent a citation. If you cannot name what establishes a claim,
  that claim is `unverified` and the `source` stays empty.
- The ledger is a superset of what `check` detects. A claim with no number in
  it — "squat rather than stoop" — still belongs there if it is contestable.
  The detector finds numbers; **you** find claims.
- If a number cannot be sourced and cannot be hedged, cut it. A script with
  no statistic beats one with a fabricated statistic.

### 2. Grade the hooks before spending anything

Read `references/engagement-rubric.md` now and score your three hooks against
it. This is free —
it is pure text. Pick the winner, make it beat 1's narration, set `chosen_hook`,
and re-run `check`.

### 3. STOP. Show the user the script and get approval.

```bash
$QV plan
```

**Do not run any further command until the user has said yes.** Everything up
to here is free; the next command spends their money and several minutes of
their time. A storyboard is a page of text — it is the cheapest possible place
to catch a wrong angle, a dull hook, or a factual call they would make
differently, and the only place where fixing one costs nothing.

Show them:

- **the angle you took, and the one you rejected.** This is the cheapest thing
  on the list to change and the most expensive to get wrong — redirecting an
  angle costs a word, rejecting a finished script costs a rewrite
- the script as prose, beat by beat
- which hook you picked and **why the other two lost** — that is the judgement
  they most often want to overrule
- **the claims ledger**, `unverified` and `contested` entries first. This is
  the part they are uniquely able to judge and the pipeline cannot check at
  all. Say plainly that nothing verified these — do not let the ledger's
  existence imply the claims were checked
- the estimated cost

Then ask plainly whether to proceed. If they want changes, edit
`storyboard.json` and show `plan` again — still free.

**The one exception:** if the user has already said to just build it, or asked
for no interruptions, take that as approval and carry on.

### 4. Narration (costs credits)

```bash
$QV narrate                # ~$0.02, gives the real duration
$QV avatar --submit        # queues the render and returns immediately
```

Narration produces the audio and word-level timestamps that drive the captions,
the b-roll cuts, and the avatar lip-sync — one clock for everything.

**Submit the avatar now, do not wait for it.** It takes minutes of pure waiting,
and choosing b-roll takes minutes of work that does not depend on it. Running
them at the same time is most of the difference between a two-minute build and
a ten-minute one. Collect it in step 6.

### 5. B-roll: search, then judge

```bash
$QV broll
```

This searches every beat and caches thumbnails. **It picks nothing.** Now do the
part that matters.

Read `references/visual-language.md` now. It covers judging footage, the
fallback ladder, writing prompts for generated shots, and diagrams — the whole
of the rest of this step.

```bash
$QV sheet          # one labelled contact sheet per beat
```

1. **Read each sheet** in `<run>/broll/sheets/` with the Read tool. Do not judge
   from filenames or query strings — actually view the images. Details in
   `<run>/broll/candidates.json`.
2. For each, score 0–3 against that beat's `visual.intent`:
   - **3** — shows exactly the described thing
   - **2** — clearly on-topic and supports the line
   - **1** — same general world, but not the described thing
   - **0** — unrelated
4. Accept the best candidate scoring **≥2**. Prefer video over stills, and
   vertical over landscape (no cropping loss).
5. If nothing scores ≥2, walk the fallback ladder — ending in a designed card,
   never a loosely-related clip.

Two or three shots deserve real motion rather than a pan — the hook, the
payoff, anything whose point *is* movement. Add `"animate"` to those picks;
`references/visual-language.md` covers when it is worth it.

Write `<run>/picks.json`:

```json
{
  "1": {"provider": "pexels", "ident": "3196036", "download_url": "..."},
  "2": {"card": true}
}
```

```bash
$QV fetch
```

### 6. Collect the avatar and build

```bash
$QV avatar --collect   # waits for the render submitted in step 4
$QV build --music auto --mood "<a few words on the feel>"
```

**Always build with a bed.** `--music auto` generates an instrumental matched
to the topic, ducked under the narration automatically. Silence between
sentences is where attention leaks, and a bed is the cheapest thing that fixes
it. `--mood` steers it — "tense and driving", "warm and steady".

### 7. Grade the result, then fix it

**This step is not optional. The first render is a draft.**

```bash
$QV verify   # every shot beside the words spoken over it
$QV grade    # mechanical checks and the scorecard
```

**`verify` is the one that catches the failures that matter.** It writes a
contact sheet pairing each shot with its narration. Look at every pair and ask
whether the shot serves *that line* — not whether it matches the beat's visual
intent, which is something you wrote and may itself be wrong.

This measures what is measurable — duration, speaking rate, dead air, black
frames, clipping, caption-band contrast — and writes `<run>/report.html` with a
frame strip. It exits non-zero on blockers.

It cannot tell you whether the video is *engaging*. So then do the part it
cannot: **view the sampled frames in `<run>/frames/`** and score against
`references/engagement-rubric.md`. Then repair:

- **Visual problems** (wrong shot, caption over a busy area, shot too long) —
  re-pick footage, re-run `fetch`, then `build`. Free. The base track is keyed
  on the cut list, so a swapped clip rebuilds automatically.
- **Script problems** (weak hook, dead air, rushed explanation) — these need a
  re-`narrate` and re-`avatar`, which costs credits again. Tell the user the
  cost before doing it.

Repeat until the video would genuinely hold someone's attention. Two or three
passes is normal.

## Cost discipline

`narrate` and `avatar` spend money; everything else is free. Get the script
right at the approval gate, and prefer visual fixes over script fixes
afterwards — footage, captions and staging can all be redone for nothing.

Never spend past the gate without saying what it will cost first. If the user
set a budget, track it and stop when it is reached rather than at the end.

## What is not in here

Everything the CLI handles for itself — API shapes, codecs, caption geometry —
lives in the code and in `docs/api-notes.md`. You never call those APIs, so
you never need those details. If a failure ever seems to need them, the error
message is the thing to fix.
