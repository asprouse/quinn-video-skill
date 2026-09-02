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

## Checking a number against a source

`quinn-video sources` lists the numeric claims that still lack a primary
source; the model searches each with `WebSearch(allowed_domains=...)` scoped
to `.gov`/`.edu` publishers, and `check` blocks a claim marked `established`
on a secondary one.

### Why domain restriction is the whole mechanism

The model was trained on the web, so open web search is not an independent
check — its errors are correlated with the model's, and it returns the same
consensus re-served with a URL. The URL is the problem: it makes a shaky
claim survive review.

Measured on two real claims from this project:

| | "29 races, 29 wins" (R32 GT-R) | "how many die from ladder falls" |
|---|---|---|
| What search returned | Fandom, enthusiast blogs, Wikipedia, the manufacturer's own heritage page | CDC MMWR, NIOSH, PMC, Cal/OSHA |
| Primary source exists | no | yes |
| Effect of retrieving | promotes an unverified claim to `established` with a citation | corrects a real error — the famous ~300 covers all settings, work-related was 113 |

The difference is not the search. It is whether a primary source exists and
is indexed. So the rule is about **where** an answer came from, never whether
one was found — and a claim with no authority publishing on it stays
`unverified`, which is the correct end state, not a gap.

### Notes from running it

- `.gov` is coarser than it looks. Restricting a biomechanics search to
  government domains returned mostly **USPTO patent applications** — a
  filing is not a finding, so `uspto.gov` and `patents.google.com` are
  excluded despite being otherwise-passing hosts.
- Wikipedia followed *out* to a primary reference counts as primary. That is
  the path a reviewer is supposed to take and must not be penalised.
- Scope errors are the common real defect, not fabrications. A figure that is
  correct for one population and wrong for the one on screen will pass every
  check here; only reading the source catches it.
