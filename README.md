# quinn-video

A Claude Code skill that turns a topic into a finished 30–60 second vertical
educational video — the kind of short-form explainer that actually holds a
viewer to the end.

Give it `ladder safety` and it returns an mp4 with a HeyGen avatar presenting,
a voiceover, word-by-word captions locked to the narration, a fast-cut
slideshow of on-topic footage, and a scorecard telling you what is still wrong
with it.

> **Status:** working end to end. Proven on two of the brief's three topics —
> ladder safety and heat safety — from a bare topic to a graded mp4.
> See [CHANGELOG.md](CHANGELOG.md).

## Install

```
/plugin marketplace add asprouse/quinn-video-skill
/plugin install quinn
```

Then ask Claude for a video and the skill drives itself. It runs the CLI out of
the plugin's own checkout, so nothing needs to be installed globally.

> Install from **GitHub**, not from a local path. A local-directory install
> copies the working tree as-is, ignoring `.gitignore` — which means `.env`,
> `runs/` and `.venv` come along too. Ours was 684 MB with live API keys in it.

## Setup

Run these **in the project you want the videos to appear in**:

```bash
export QV="uv run --project ${CLAUDE_PLUGIN_ROOT} quinn-video"

cp "${CLAUDE_PLUGIN_ROOT}/.env.example" .env   # add HEYGEN_API_KEY, PEXELS_API_KEY
$QV fonts                                       # typefaces, once per machine
$QV doctor                                      # toolchain, credentials, balance
```

`doctor` runs before anything that costs money, and reports the HeyGen balance
and how many renders it affords. Pick a presenter with `--list-avatars` and
`--list-voices`, and put the ids in `.env`.

Everything the run produces — `runs/`, footage, the scorecard — lands beside
your project. Only the code lives in the plugin.

### Working on the skill itself

From a checkout, `uv run quinn-video …` works directly and no `--project` is
needed.

## How it works

```
topic
 ├─ script      Claude writes storyboard.json — beats, visual intent, 3 hooks
 ├─ pre-grade   hooks and pacing scored on text alone (free)
 ├─ voice       HeyGen TTS → audio + word-level timestamps
 ├─ avatar      alpha-WebM presenter, lip-synced to that exact audio
 ├─ b-roll      Pexels search → Claude judges thumbnails → generate → card
 ├─ compose     ffmpeg: b-roll base → avatar overlay → captions → ducked music
 └─ grade       frame sampling → report.html → targeted repair
```

The design turns on one fact: HeyGen's speech endpoint returns **word-level
timestamps**. Generating narration separately and feeding that audio to the
avatar means captions, b-roll cuts, and lip-sync all derive from a single
clock, so nothing can drift.

Two responsibilities are kept apart on purpose. The scripts do what is
mechanical and deterministic. Claude does what is judgement — writing a script
worth watching, and deciding whether a clip actually shows what a line
describes. Search relevance cannot answer the second one, and it is the
requirement the brief states most sharply: *nothing random or unrelated*.

## Usage

Ask Claude for a video and the skill drives itself. To run the stages by hand:

```bash
$QV init "ladder safety"                  # create a run directory
# write storyboard.json into it
$QV check                  # validate and check pacing
$QV narrate                # costs credits
$QV broll                  # search + cache thumbnails
# review thumbnails, write picks.json
$QV fetch
$QV avatar                 # costs credits
$QV build
$QV verify                 # every shot beside its narration
$QV grade                  # writes report.html
$QV status                 # what this run has produced
```

Every stage caches. Re-running is cheap and safe, and the two stages that spend
money never re-run because something downstream broke.

## Requirements

- `ffmpeg` with VP9 decode and libx264 — the default Homebrew bottle is fine.
  Captions are rendered with Pillow, so no `libass` build is needed.
- `uv`
- A HeyGen account (a matting-trained avatar, for transparent output) and a
  free Pexels API key
- Optionally `FAL_KEY`, for generated b-roll (~$0.05 a shot) where stock has
  nothing honest to offer

## Development

```bash
uv sync
uv run pytest tests -q
uvx ruff check src tests
claude plugin eval evals/ --allow-tools Bash Write Edit
```

## License

MIT. Bundled typefaces (Montserrat, Anton) are SIL Open Font License 1.1 and
are downloaded at setup rather than committed.
