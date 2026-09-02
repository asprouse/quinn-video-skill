# The claims ledger

## What this is not

**It does not verify facts.** It cannot. There is no retrieval, no source
lookup, no cross-check against any authority. A claim marked `established`
with a plausible-looking source is exactly as unverified as one marked
`unverified` — the difference is only what the model asserted about it.

This is worth stating plainly because a ledger creates an impression of
diligence that the mechanism does not earn. The output says so at the
approval gate for the same reason.

## What it is

These videos state things confidently, and confidence is most of what makes
them watchable. Every mechanical check in this pipeline is about *mechanics*:
duration, sync, black frames, whether the footage matches the beat. The
script itself was taken entirely on trust, and a wrong number in a safety
video is worse than a dull one.

There is also a structural pull towards inventing statistics. The engagement
rubric rewards punchy specificity, and the script guidance says *"give the
real number, or no number"*. Together they select for confident round figures
— which is precisely where a fabricated one hides.

So the storyboard carries a ledger of what it asserts and where each
assertion came from, and it is printed at the approval gate. The point is
that the person paying for the render is **deciding about a listed claim**
rather than scanning prose for numbers.

## Division of labour

Judging what a claim is and where it came from is the **model's** job.
Detecting that a beat asserts something the ledger never mentions is the
**checker's** job — that part is mechanical and cannot be argued with, which
is what stops the ledger becoming optional.

`claims.assertions()` scans narration *and* overlay text for numbers (spelled
out as well as digits, since scripts spell them for the speech engine),
ratios, named standards, and universals like "always" or "leading cause". It
is deliberately over-eager: a false positive costs one ledger line saying
"procedural, not a statistic", a false negative is a number nobody looked at.
Same trade as the cache fingerprints.

## Status vocabulary

| status | means |
|---|---|
| `established` | documented in a standard, regulation or published dataset — **requires a source** |
| `contested` | real, but disputed or a simplification of a contested picture |
| `estimate` | a rule of thumb; the narration must hedge it |
| `unverified` | from model recall, not confirmed against a source |
| `illustrative` | arithmetic derived from another claim, or a procedural instruction |

`unverified` is the honest default for most claims and is **not** a failure
state. Relabelling a recalled figure as `established` to clear the check is
the worst available move: it converts "nobody has checked this" into "this is
documented".

## What blocks, what warns

Blocks (`check` exits 2):

- a beat asserting something with no ledger entry at all
- a claim marked `established` with no source — saying a claim is established
  is itself a claim
- a claim pointing at a beat that does not exist

Warns:

- `estimate` stated flatly, with no hedge in the narration. This directly
  targets the confident-round-number failure mode above.
- any `unverified` claims present, listed together at the gate
- a beat with more distinct assertions than ledger entries

## The remaining hole

Nothing detects a **fabricated source**. The `established`-needs-a-source
rule raises the bar from passive omission to active invention, and the gate
shows the source text so a reader can judge it — but a determined
confabulation passes. Closing it needs retrieval, which is the next step up
and is not built.

## Checking a citation against the regulation

`docs/claims.md` above describes a ledger that records provenance without
checking it. For federal regulations, that check is now possible:

```bash
quinn-video cfr "29 CFR 1926.1053(b)(5)(i)"            # read the rule
quinn-video cfr --find "points of contact" --in "29 CFR 1926"
quinn-video sources                                     # check the ledger
```

Text comes from the eCFR API — free, no key, and the authoritative publisher.
Notes from building against it: it **requires** a compressed response and
returns an error explaining so otherwise; whole parts are megabytes and it
sheds load on them, returning intermittent 503s for a URL that succeeds
moments later, so requests retry with backoff; and part XML is cached on the
date the title was last amended, which is the only key that neither
re-downloads daily nor serves last year's text forever.

**What this closes and what it does not.** A citation naming a section that
does not exist is now a blocker — mechanical, unarguable. But a citation can
resolve perfectly and still not support the claim:

```
beat 3: three points of contact is required on ladders
  cited as 29 CFR 1926.1053(b)(22) — § 1926.1053 Ladders.
    (22) An employee shall not carry any object or load that could cause
         the employee to lose balance and fall.
```

That citation is real, that paragraph is real, and it says something else.
No mechanism detects this; the text is printed beside the claim so a reader
sees it. Retrieval narrows the hole from "was this invented?" to "does the
source say this?" — which is a reading question, and a much easier one.

**Coverage is uneven, deliberately.** This checks federal regulations. It has
nothing to say about biomechanics, injury statistics, or anything outside the
CFR, and it must not be read as a general fact-check. Claims without a
regulatory source stay `unverified` — that is the honest state, not a gap to
paper over.
