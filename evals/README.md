# Evals

Run with:

```bash
claude plugin eval evals/ --allow-tools Bash Write Edit
```

The cases deliberately stop short of anything that spends HeyGen or Pexels
credits. They test the two judgements the skill exists to make — writing a
script worth watching, and refusing footage that is merely adjacent to the
subject — rather than the mechanics, which the pytest suite covers.
