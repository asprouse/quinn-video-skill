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

## One beat per visual idea

A beat is a unit of *picture*, not of grammar. If a line names two different
things, it needs two beats, because the cut list divides a beat's time evenly
between its clips — and an even split almost never falls where the sentence
boundary does.

The failure, from a real build: one beat carried *"So which is faster?
Whichever one matches your track. Corners belong to Godzilla. The straight line
belongs to the Supra."* Two clips were supplied, GT-R then Supra, and the
midpoint split put the Supra on screen for "Corners belong to Godzilla". The
payoff line — the one the whole video builds to — named one car and showed the
other.

Split it into three beats, one per idea, and each line lands on its own shot.

**Splitting is free if you split at a sentence boundary.** The narration is the
beats concatenated, so cutting a beat in two at a full stop leaves the text
byte-identical — the audio and the avatar render stay cached and nothing is
re-bought. Restructuring beats costs nothing; only changing words costs money.

## Pacing

- Target **165–180 wpm**. Short-form narration is faster than conversation.
  Below ~155 it reads as lethargic no matter how good the writing is — and
  that is a delivery problem you can fix for three cents, because re-narrating
  is nearly free. `narrate` reports the rate it achieved; if it comes in slow,
  raise `QUINN_VOICE_SPEED` and run it again before spending on the avatar.
- 45s ≈ **125 words**. That is the whole budget. It is less than it sounds.
- `quinn-video check` reports the estimate. Fix the length before paying for
  audio — you cannot trim it afterwards.
- Vary sentence length. A run of same-length sentences flattens into drone.
  Short. Short. Then a longer one that carries the actual explanation. Short.

## Pick the angle the audience already cares about

Before the hook, decide what the video is *about*. Most topics have an
obvious angle and a clever one, and the clever one is usually worse.

The failure to avoid: asked for "Supra vs Skyline GT-R", a first draft went
after Japan's gentlemen's agreement — the 276 hp cap both cars advertised.
Genuinely interesting, verifiably true, and the wrong video. What those two
cars are *famous for* is the GT-R's all-wheel drive and its touring-car
record, and the Supra's engine and the drag strip. That is the angle the
audience arrives with, and the one they will argue about in the comments.

**Ask what each subject is actually known for**, and build on that. Reach for
the obscure fact only when the obvious angle is exhausted or wrong.

For **"X vs Y"** specifically, the strongest structure is almost always:

1. Pose the comparison as a question — "Which is faster?"
2. Refuse the premise — "Wrong question. Ask *where*."
3. Give each side its own domain, with its real résumé as evidence
4. Answer honestly: it depends, and here is what it depends on

That beats picking a winner, which invites an argument the video cannot
settle, and it beats a trivia angle, which answers a question nobody asked.

**Offer the angle at the approval gate, not just the script.** Say which angle
you took and which you rejected, the way you do for hooks. Redirecting an
angle costs the user a word; rejecting a finished script costs a rewrite.

## Say what it is before you say what is interesting about it

A hook that violates an expectation only lands if the viewer knows whose
expectation is being violated. "On paper, these two made the exact same power"
is a good sentence attached to nothing — three seconds in, the viewer does not
know what *these* are, so there is no expectation to violate yet.

**Name the subject in the first sentence.** Not a preamble about it — the
subject itself, inside the hook:

- Not "On paper, these two made the exact same power." → **"A Supra and a
  Skyline GT-R made the exact same power on paper. Both were lying."**
- Not "It kills more people than you would think." → **"Ladders kill more
  people than falls from height."**

This matters most for comparisons, where the whole idea is a relationship
between two named things. If the topic is "X vs Y", both names belong in the
first line.

**Test:** read the first sentence alone, cold. If someone could not say what
the video is about, it is not a hook yet.

## Hooks

Write **three**, grade them, ship one. The hook does one job: make the next
three seconds feel necessary.

Patterns that work:

- **Violated expectation** — "Almost nobody who dies on a ladder was high up."
- **Specific number** — "Three hundred people. Every year." Specific beats round.
- **Direct threat** — "The rung you think is safe is the one that kills you."
- **Open loop** — "There's one rule that prevents most ladder deaths." Then pay
  it off. Do not leave the loop open past ~10s.
- **The question, refused** — "Which is faster, a GT-R or a Supra? Wrong
  question. Ask where." Strong for comparisons: it states the argument the
  viewer already has, then redirects it in three words. The refusal must not
  answer itself — "it depends whether the track turns" gives away the payoff
  before the viewer has invested anything.

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

## Write for the loop

Short-form autoplays. The video restarts the moment it ends, so the last line
is followed immediately by the first — and that seam is either deliberate or
it reads as a glitch and gets swiped.

Two rules, both free:

- **The closing line hands back to the hook.** Not a cliffhanger and not a
  repeat: a resolution that leaves the opening question sounding worth asking
  again. "Thirty seconds of setup. That is the whole job." into "How high do
  you have to be for a ladder to kill you?" reads as intentional. The
  question-refused hook is well suited to this — a loop back into a question
  feels like structure rather than an accident.
- **The closing shot echoes the opening one.** Same subject, corrected. A
  badly-set ladder opens and a correctly-set one closes; a load held at arm's
  length opens and one held close finishes. The rhyme does the work of an
  ending without needing a title card.

What not to do: chase a *seamless* loop, where the join is meant to be
invisible. That works for ambient footage and not for a narrated explainer —
a human voice restarting mid-thought is always audible, and hiding the seam
means giving up the payoff. End the video properly; just end it somewhere the
hook can follow.

The compositor already holds the last frame and resolves the bed under it, so
the beat between payoff and hook is there. These rules are about making that
beat land on something.

## Safety-training specifics

These videos teach people how not to get hurt. Accuracy is not a nice-to-have.

- Give the real number, or no number. Never invent a statistic.
- Every assertion goes in `claims[]` with its provenance, and `check` blocks
  on one that does not. Note the pull this section creates: "give the real
  number" plus a rubric that rewards punchy specificity selects for confident
  round figures, which is exactly where a fabricated one hides. The ledger is
  the counterweight — if you cannot say where a number came from, mark it
  `unverified` and hedge it, or cut it.
- Where a rule comes from a standard, state the rule correctly, and check
  that the standard is the one you think it is. Worked example: the 4-to-1
  ladder ratio really is regulatory text -- 29 CFR 1926.1053(b)(5)(i), "the
  horizontal distance from the top support to the foot of the ladder is
  approximately one-quarter of the working length". "Three points of contact"
  is taught alongside it and reads like it comes from the same place, but it
  does not appear in that standard at all. Attaching a real citation to a
  claim it does not support is the failure mode to watch for -- it is more
  convincing than an invented statistic and harder to spot.
- Do not show the unsafe act as the last thing on screen. End on the correct
  behaviour — that is what gets remembered.
