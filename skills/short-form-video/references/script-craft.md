# Script craft

The script decides whether the video works. Everything downstream — avatar,
captions, footage — is production. This is the writing.

## The shape

A 30–60s explainer that lands has four movements:

1. **Hook** (0–3s) — a reason to not swipe.
2. **Stakes** (3–10s) — why this matters to *you*, specifically.
3. **Payload** (10–40s) — the one idea, made concrete and actionable.
4. **Landing** (last 5s) — a single thing to remember or do.

**One idea per video.** "Ladder safety" is a category, not a topic. "The 4-to-1
rule" is a topic. If you are teaching three rules, you are making three videos
or a bad one.

## Pacing

- Target **165 wpm**. Short-form narration is faster than conversation; under
  ~140 wpm it reads as a lecture.
- 45s ≈ **125 words**. That is the whole budget. It is less than it sounds.
- `quinn-video check` reports the estimate. Fix the length before paying for
  audio — you cannot trim it afterwards.
- Vary sentence length. A run of same-length sentences flattens into drone.
  Short. Short. Then a longer one that carries the actual explanation. Short.

## Hooks

Write **three**, grade them, ship one. The hook does one job: make the next
three seconds feel necessary.

Patterns that work:

- **Violated expectation** — "Almost nobody who dies on a ladder was high up."
- **Specific number** — "Three hundred people. Every year." Specific beats round.
- **Direct threat** — "The rung you think is safe is the one that kills you."
- **Open loop** — "There's one rule that prevents most ladder deaths." Then pay
  it off. Do not leave the loop open past ~10s.

Patterns that fail:

- Throat-clearing: "Today we're going to talk about..." Nobody stayed.
- Generic address: "Safety is important." No it isn't, not yet.
- Front-loading credentials or context before the reason to care.

**Test:** if the first sentence would work equally well on any other topic,
it is not a hook.

## Writing for the ear and the caption

The narration is heard *and* read one word at a time. That has consequences:

- **Numbers**: write "three hundred" not "300" where you want it spoken
  cleanly. TTS expands numerals, and the aligner handles it, but you lose
  control of the phrasing.
- **Front-load the emphasis word.** Captions reveal left to right, so
  "Six feet is enough to kill you" beats "It only takes six feet to kill you" —
  the punch arrives sooner.
- **Avoid subordinate clauses.** They read fine and listen badly.
- **Say "you".** Second person, present tense, active voice.

## Concreteness

Abstractions do not teach and do not hold attention.

- Not "maintain proper ladder angle" → "for every four feet up, pull the base
  one foot out"
- Not "stay hydrated" → "a cup of water every fifteen minutes, before you feel
  thirsty"
- Not "use proper lifting technique" → "the load goes between your knees, not
  in front of them"

Every beat should be *filmable*. If you cannot picture the shot, the b-roll
stage will not find one either — and the `visual.intent` you write is what
the footage gets judged against.

## Safety-training specifics

These videos teach people how not to get hurt. Accuracy is not a nice-to-have.

- Give the real number, or no number. Never invent a statistic.
- Where a rule comes from a standard, state the rule correctly (the 4-to-1
  ladder ratio, three points of contact, etc.).
- Do not show the unsafe act as the last thing on screen. End on the correct
  behaviour — that is what gets remembered.
