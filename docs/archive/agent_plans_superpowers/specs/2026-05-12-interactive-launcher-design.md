# Interactive Launcher + CPU vs GPU Compare — Design Spec
**Date:** 2026-05-12
**Status:** Approved

---

## Goal

Replace the current `run_local_demo.sh` / `run_local_demo.bat` pair with a single interactive Python launcher that guides the user through options, runs one or both separations (CPU and/or GPU), prints a timing comparison, and opens a combined browser view — all from one command with no extra steps.

---

## Architecture

### New / Changed Files

| File | Change | Purpose |
|------|--------|---------|
| `launch.py` | **New** | Interactive launcher — owns the full flow |
| `run_local_demo.sh` | **Simplified** | 3-line wrapper: finds Python, execs `launch.py` |
| `run_local_demo.bat` | **Simplified** | 3-line wrapper: calls `python launch.py %*` |
| `scripts/ui/serve_compare_demo.py` | **Extended** | Accepts optional `--artifact2` path |
| `ui/compare/index.html` | **Extended** | Dual-artifact layout when `artifact2` param present |
| `ui/compare/compare.js` | **Extended** | Renders two-column CPU vs GPU view |

### Entry Points

```
bash run_local_demo.sh          # Linux / WSL
.\run_local_demo.bat            # Windows PowerShell
python launch.py                # direct (any platform)
```

All three resolve to `launch.py` with system Python (no venv required to start).

### Wrapper Contents

```bash
# run_local_demo.sh
#!/usr/bin/env bash
exec python3 "$(dirname "$0")/launch.py" "$@"
```

```bat
REM run_local_demo.bat
@echo off
python "%~dp0launch.py" %*
```

---

## launch.py — Interactive CLI Dashboard

### Dependencies
Stdlib only (`os`, `sys`, `subprocess`, `pathlib`, `json`, `shutil`, `time`). Runs before the venv exists.

### Dashboard Screen

Rendered on launch and re-rendered after every keypress. Uses ANSI escape codes for color (works on WSL bash and Windows Terminal / PowerShell with VT processing enabled).

```
┌─────────────────────────────────────────────────┐
│       Audio Source Separation Demo              │
├─────────────────────────────────────────────────┤
│                                                 │
│  Source   (1) MP3   2 Video   3 Mic            │
│  Input    fixtures/audio/demo_mix.mp3  [F]ile  │
│  Mode     (A) Smoke   B Full                   │
│  Device   X CPU   Y GPU   (Z) Both ◄ compare   │
│                                                 │
│  ─────────────────────────────────────────────  │
│  R  Run     Q  Quit                             │
└─────────────────────────────────────────────────┘
```

**Keys:**
- `1` / `2` / `3` — set source mode (MP3 / Video / Mic)
- `A` / `B` — set runtime mode (Smoke / Full)
- `X` / `Y` / `Z` — set device (CPU / GPU / Both)
- `F` — drop to a line prompt for a custom file path, return to dashboard
- `R` — run with current settings
- `Q` — quit

**Current selection** shown with parentheses `(1)` and bright color. Unselected options rendered dim.

**Unavailable options** shown greyed with inline reason:
- `B Full [no model]` when `artifacts/models/umx-live.pt` is missing
- `Y GPU [no CUDA]` / `Z Both [no CUDA]` when torch cannot detect a GPU (checked at startup with a subprocess call into the venv, if it exists)

### Input File Selection (`F`)

Dashboard clears and shows:
```
  Enter path to audio or video file (Enter to cancel):
  > _
```
Accepts absolute or relative paths. Validates the file exists before returning to the dashboard. On cancel (empty Enter), restores previous value.

### Default Settings

| Setting | Default |
|---------|---------|
| Source | MP3 |
| Input | `fixtures/audio/demo_mix.mp3` |
| Mode | Smoke |
| Device | CPU |

---

## Run Flow (when R is pressed)

The dashboard clears and the launcher runs each step sequentially, printing live status:

```
  Setting up environment...              ✓  (or shows pip progress)
  Running CPU separation...              ✓  1842 ms
  Running GPU separation...              ✓   312 ms
  ─────────────────────────────────────────────────
  GPU is 5.7× faster  (infer: 1785 ms → 255 ms)
  ─────────────────────────────────────────────────
  Opening browser → http://127.0.0.1:8000/ui/compare/...
  Press Ctrl+C to stop the server.
```

### Step 1 — Environment Setup

Creates `.venv` with system Python if it doesn't already exist, then runs `pip install -e .[dev]` inside it. Skipped if `.venv/bin/python` (Linux) or `.venv\Scripts\python.exe` (Windows) is already present. pip output suppressed unless an error occurs.

### Step 2 — Separation Run(s)

Each run calls `scripts/live/run_live_separation.py` with appropriate args.

**Output directories:**
- CPU-only or single run: `artifacts/live/one-click/`
- GPU-only: `artifacts/live/one-click/`
- Both: `artifacts/live/cpu-run/` and `artifacts/live/gpu-run/`

**Timing** is read from `total_ms` and `metadata.stages` in the written JSON artifact.

**Speedup line** (shown only when Both was selected):
```
GPU is {X}× faster  (infer: {cpu_infer} ms → {gpu_infer} ms)
```

### Step 3 — GPU Failure Handling

If the GPU run exits non-zero or the artifact contains `"status": "error"`, the launcher:
1. Prints the error reason from the artifact's `error_message` field
2. Continues — opens the compare UI with CPU-only results
3. Does NOT crash or require re-running

### Step 4 — Browser Open

Constructs the URL and opens it:

- Single run: `?artifact=/artifacts/live/one-click/live_runtime_result.json`
- Both: `?artifact=/artifacts/live/cpu-run/live_runtime_result.json&artifact2=/artifacts/live/gpu-run/live_runtime_result.json`

Then starts `serve_compare_demo.py` in the foreground (Ctrl+C to stop).

---

## serve_compare_demo.py Extension

Adds an optional `--artifact2` CLI argument. When provided, it is validated (must be inside the project root) and URL-encoded the same way as `--artifact`. The constructed URL includes both params. No other behavior changes.

---

## Compare UI Extension

### URL Contract

```
/ui/compare/?artifact=<path>              # existing — single run
/ui/compare/?artifact=<path>&artifact2=<path>  # new — dual run
```

### Layout (dual mode)

When `artifact2` is present, the page renders a two-column layout:

```
┌─────────────────────────────────────────┐
│  CPU  1842 ms total  |  GPU  312 ms total │
│        ══ GPU is 5.7× faster ══          │
├──────────────────────┬──────────────────┤
│  Vocals  [waveform]  │  Vocals [waveform]│
│  Drums   [waveform]  │  Drums  [waveform]│
│  Bass    [waveform]  │  Bass   [waveform]│
│  Other   [waveform]  │  Other  [waveform]│
└──────────────────────┴──────────────────┘
```

- Timing header bar spans both columns
- Speedup shown prominently between the two panels
- Each column is independently playable
- Column headers are `CPU` / `GPU` (derived from `metadata.device_used` in the artifact)

### Single-artifact behavior

When `artifact2` is absent, the page renders exactly as it does today — no visual or behavioral changes. Existing tests are unaffected.

### Implementation approach

`compare.js` checks `URLSearchParams` for `artifact2` on load. If present, it fetches both artifacts in parallel and calls a `renderDual(artifact1, artifact2)` path. If absent, it calls the existing `renderSingle(artifact)` path. The two paths share the waveform rendering component.

---

## Error Handling Summary

| Situation | Behavior |
|-----------|----------|
| Model missing, Full mode selected | Option greyed out in dashboard with `[no model]` label |
| No CUDA, GPU/Both selected | Option greyed out with `[no CUDA]` label |
| GPU run fails at runtime | Print error reason, open browser with CPU results only |
| File path not found (F prompt) | Re-prompt with inline error message |
| Port 8000 already in use | Print clear error, suggest `--ui-port` flag |

---

## Out of Scope

- Arrow-key navigation (single-keypress letter/number selection only)
- Parallel CPU+GPU execution (sequential is fairer for comparison)
- Audio playback in the terminal
- Any changes to existing benchmark or evaluation scripts
