# Visual language

## Write the intent from the line, not from what is findable

`visual.intent` is what every downstream check judges against — so if the
intent does not serve the narration, everything passes and the video still
shows the wrong thing.

The failure to avoid, from this project: a beat whose line was *"you don't
have to be high up to **die falling off** a ladder"* carried the intent *"a
worker standing on a low stepladder."* It captured "not high up" and dropped
the death. The finished video contained no danger anywhere, and nothing
flagged it, because every shot matched its intent exactly.

That intent was phrased to be **findable in a stock library**. Once footage can
be generated, findability is no longer the constraint — so write the intent as
what the line *needs the viewer to see*, then let sourcing worry about how.
Ask of every beat: if the narration names a consequence, is the consequence on
screen?

Then check the result with `quinn-video verify`, which pairs every shot with
the words actually spoken over it. Judge the pairing, not the intent.

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
4. **Generate the shot** — `{"generate": "<prompt>"}` in picks.json, if `FAL_KEY`
   is set. See below; this is often better than step 1, not a last resort.
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

## Generated b-roll

With `FAL_KEY` set, a beat can generate its own footage:

```json
"5": [{"generate": "A worker in a hi-vis vest crouches to set the feet of an
        aluminium extension ladder on concrete."}]
```

Stills, not clips — about $0.05 each. They cost a fraction of generated video,
the pipeline already gives stills a Ken Burns move, and they avoid the morphing
hands and warping rails video models still produce.

**Generate poses and scenes, not events.** The model draws a *state*, not a
happening. "A worker overreaching, the stepladder tilting onto two legs" works
— it is a pose. "A ladder skidding out from under him" does not — it is an
event, and comes back as an ordinary photo of someone climbing.

**Describe the hazard, not the injury.** Safety filters block prompts about
people falling or being hurt, and fal returns a blank black frame when they
fire. "Overreaching", "off balance", "tilting onto two legs" all pass and show
the same danger. The generator detects the blank frame, retries, and says so
rather than letting it ship.

**Draw several and choose.** A single draw is a lottery. One prompt, three
draws, produced a ladder correctly resting on a wall, a ladder floating in
front of one, and a ladder standing bolt upright. No wording removes that
variance. `quinn-video candidates --beat 4` draws three; pick one with
`"variant": "b"` on the pick. This matters more than which model you use.

**Describe the negative space, not the contact points.** Spatial relationships
are where these models are weakest, and two competing constraints make it
worse: "top rails pressed against the brickwork" *and* "feet a stride away"
produced ladders standing bolt upright — the model satisfied the first and
dropped the second. Naming the shape of the gap instead — "forming an obvious
triangle of empty space between the ladder, the wall and the ground" — got it
right three times out of three.

**Models differ on physical plausibility.** On the same contact prompt,
Seedream 4 placed the ladder against the wall correctly twice out of two;
flux-pro ultra managed one of two. Ultra holds more detail. Set `"model"` on a
pick to override per shot.

**Anatomy fails on unusual poses, and no prompt fixes it.** Asking for an arm
held straight out with a flat palm on a rung returned an arm raised overhead
with the elbow bent backwards. Common poses — climbing, crouching, carrying,
reaching up — are reliable. Anything a stock photographer would have to pose
deliberately is not, and belongs in `diagrams`.

**Generate scenes. Draw procedures.** This is the line that matters, and it was
found the hard way. An ordinary scene — someone climbing a ladder, someone
setting its feet down — comes back better than anything in the stock libraries.
A specific physical technique does not: asked for a worker holding the
toes-to-palms angle check, the model returned a man gesturing at a stepladder,
and a *more* prescriptive prompt made it drop the person entirely. Anything
where the exact pose or geometry is the teaching point belongs in `diagrams`.

**Check generated footage harder than stock, not more leniently.** A generated
clip showing bad practice is worse than an off-topic one, because it looks
authoritative. The first attempt at "worker climbing a ladder" came back with
the ladder nearly flat against the wall — an unsafe setup, on screen, while the
narration said to set the angle. Naming the geometry in the prompt ("leaning at
a clearly slanted angle, its base set well out from the wall") fixed it. Judge
every generated shot against the *claim the narration is making*, not just its
subject.

Prompts are saved next to each image as a `.txt`, so a reviewer can see what was
asked for and judge the result against it.

## Annotating a real photograph

Better than cutting away to a drawing on black: draw the rule onto an actual
ladder, so the video never leaves the world it is teaching about.

```json
"3": [{"generate": "An aluminium extension ladder propped against a plain wall...",
       "annotate": {"kind": "ladder-angle", "ratio": [4, 1],
                    "base": [0.68, 0.90], "top": [0.36, 0.145],
                    "for_image": "73246695"}}]
```

`base` and `top` are the ladder's feet and its contact with the wall, in
normalised 0–1 frame coordinates. **Read them off the image by eye** — generate
the photo first, look at it, then write the numbers. They cannot be detected
reliably, and a wrong anchor draws a confident annotation in the wrong place.

Two things this needs to be safe:

- **Check the photograph actually shows the right angle.** Image models will
  happily return a ladder flat against a wall. Annotating that with "4:1" would
  teach the wrong thing with an authoritative label on it. The renderer refuses
  if the anchors imply a ratio more than 25% off the rule.
- **Pin the anchors with `for_image`.** Generation is not deterministic, so the
  photo can change under coordinates measured on an older one. The build refuses
  on a mismatch and tells you to re-measure.

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

## What you do not control

Captions, cut rhythm and avatar staging are all derived from the word
timestamps and handled for you. You cannot author them, so the reference is
only what to *do* when one of them goes wrong:

- **A caption is hard to read** — the fix is almost always the footage, not the
  caption. Pick a shot with a calmer lower third.
- **The presenter covers the subject** — if the important thing in a shot sits
  bottom-right, choose different footage for that beat.
- **A beat feels static** — give it more than one clip in `picks.json`. Shots
  are capped at four seconds, so a long beat with a single clip repeats it.

The parameters behind all three, and the reasoning for them, live in the code.
