# MUSDB18 Placeholder Layout

This repository uses a minimal directory placeholder so dry-run evaluation commands can execute in CI/local smoke mode without bundling MUSDB18 audio.

Expected real dataset layout for full eval runs:

- `data/musdb18/test/<TrackName>/...`

For smoke mode in this slice, only the directory names are required by `scripts/eval/run_umx_eval.py`.
