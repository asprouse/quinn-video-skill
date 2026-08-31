# Visual language

## Judging b-roll

The brief's hardest requirement is negative: *"All imagery and background
footage is on-topic. Nothing random or unrelated."*

Search cannot deliver that. Query "ladder safety" and stock libraries return
handshakes, generic hard-hat portraits, and sunsets. **You** are the filter.

**Always view the thumbnail.** Never judge from the query string or filename —
that is how unrelated footage ships.

Score against the beat's `visual.intent`:

| Score | Meaning | Use it? |
|-------|---------|---------|
| 3 | Shows exactly the described thing | Yes |
| 2 | Clearly on-topic, supports the line | Yes |
| 1 | Same general world, not the described thing | **No** |
| 0 | Unrelated | **No** |

Score 1 is the dangerous one. A generic shot of a construction site while the
narration explains a ladder angle is *technically* on-theme and still reads as
filler. Reject it.

Tie-breakers, in order: video over still; vertical over landscape (no crop
loss); a shot with human action over an empty scene; clear subject over a busy
composition that will fight the captions.

## The fallback ladder

When nothing scores ≥2, walk this in order. Do not stop early and do not settle.

1. **Rephrase the query.** Describe the *action*, not the topic. "ladder
   safety" finds nothing; "worker climbing ladder" finds plenty. Drop abstract
   nouns, add verbs and objects.
2. **Try the other medium.** A strong photograph with a Ken Burns move beats a
   weak video. `broll` already searches stills when video comes up short.
3. **Try the secondary provider** (Pixabay, if `PIXABAY_API_KEY` is set).
4. **Generative clip** — only if `FAL_KEY` or `REPLICATE_API_TOKEN` is set.
5. **Designed card** — `{"card": true}` in picks.json.

The card is a real answer, not a failure. A typographic frame reads as an
editorial choice; a wrong clip reads as a mistake. Given the choice between an
honest card and an adjacent stock shot, take the card every time.

## Beat overlays and emphasis

Two authored fields reach the screen beyond the footage itself:

- **`overlay`** with kind `stat` or `label` holds a line in the upper third for
  the length of the beat, fading in and out. Use it for the one number the beat
  turns on — `"161 deaths in one year"` — not for restating the narration.
- **`emphasis`** lists words that keep the accent colour *after* being spoken,
  instead of reverting to white with the rest of the phrase. Two or three per
  beat at most; accenting everything accents nothing.

Emphasis matches **spoken** words, so spell numerals the way the voice says
them. `check` warns about terms it cannot find.

## Generated diagrams

Some ideas are geometric, and no stock library has footage of them. A rule
about an angle, a ratio, or a distance is better *drawn* than illustrated with
a photograph of something nearby.

Set the beat's overlay kind to `ladder-angle` and it generates an animated
diagram instead of sourcing footage: ground and wall draw in, the ladder swings
out to the correct angle, then the rise and run dimensions annotate themselves.

```json
"overlay": { "kind": "ladder-angle", "text": "4 : 1", "ratio": [4, 1] }
```

Time it against the narration. The build treats a generated clip as **one
shot** rather than cutting it into fragments, so the animation plays once,
start to finish, across the whole beat — give it a beat of 4-6s and write the
narration so the rule is spoken while the diagram draws it.

Everything in the diagram stays above y=1000, clear of the caption line and the
cornered presenter. When adding new diagrams, keep to that band.

## Captions

Handled automatically from the word timestamps — you do not author these. What
they do, so you can judge them:

- Phrases of up to 4 words, broken on pauses over 320ms and on sentence ends.
- Words appear one at a time; the spoken word is accented in high-visibility
  yellow (`#FFD600`, borrowed from safety vests so the accent feels native).
- The phrase is laid out once and words appear **in place**, so the line builds
  left to right the way it is read. Re-centring the visible words on every beat
  keeps a short line optically centred, but it drags the words already on
  screen leftwards — and the eye reads that drift as the text arriving right to
  left, which is backwards for English.
- Heavy stroke plus drop shadow, because the background is unpredictable.
- Positioned clear of platform UI: bottom 340px, top 120px, right 200px.

If captions are hard to read in a frame, the fix is usually the *footage* —
pick a shot with a calmer lower third — not the caption style.

## Avatar staging

The presenter is a transparent WebM composited over the b-roll, so we control
where it sits.

Default: **full-bleed for the hook, corner for the rest.** The first three
seconds decide whether anyone watches, and a face at full size is the strongest
thing available. After that the b-roll is doing the teaching and the presenter
shrinks to ~42% width, bottom right.

Sizes cut rather than animate. A hard size change lands as an edit; ffmpeg
cannot smoothly animate a scale anyway.

Watch for the presenter covering the subject of the shot. If the important
thing in the footage is bottom-right, move the avatar or pick different
footage.

## Cut rhythm

- No shot longer than **4 seconds**. Longer beats are split across repeats of
  their own clip, alternating the Ken Burns direction so it does not read as a
  loop.
- Cuts land on beat boundaries, which land on phrase boundaries, because
  everything derives from the same word timestamps.
- Stills always move. A static frame in a fast-cut sequence reads as a stall.
