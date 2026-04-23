# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

Reproducible evaluation and benchmarking harness for audio source separation models (UMX/Demucs). The project validates model inference pipelines — from ONNX export through TensorRT build — and runs live separation contracts against MP3, mic, and video sources, producing structured JSON artifacts at each stage.

## Setup

```bash
# Install core deps + dev extras
pip install -e .[dev]

# Install mic-capture support (optional, needs PortAudio)
pip install -e .[mic]
```

The project uses `setuptools` (not poetry). Python `>=3.10,<3.13` is required.

## Key Commands

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=live_runtime --cov=scripts -v

# Slice verifiers (run these to validate full contracts)
bash scripts/verify/s01_check.sh       # ONNX export + schema
bash scripts/verify/s02_check.sh       # Live MP3 → four-stem
bash scripts/verify/m002_s01_check.sh  # Demucs live-runtime contract
bash scripts/verify/s06_check.sh       # Final capstone evidence bundle

# Dry-run ONNX export (CI-safe, no GPU needed)
python scripts/export/export_umx_onnx.py \
  --onnx-output artifacts/export/umx-smoke.onnx \
  --input-shape 1,2,44100 --min-shape 1,2,22050 \
  --opt-shape 1,2,44100 --max-shape 1,2,88200 --dry-run

# GPU TensorRT build (requires trtexec on PATH)
bash scripts/export/build_trt_engine.sh \
  --onnx artifacts/export/umx-smoke.onnx \
  --engine artifacts/bench/trt/umx-smoke.engine \
  --min-shape 1x2x22050 --opt-shape 1x2x44100 --max-shape 1x2x88200 --fp16

# Compare UI demo server
python scripts/ui/serve_compare_demo.py
```

## Architecture

```
live_runtime/        # Core runtime package (importable)
  contracts.py       # Frozen dataclasses: LiveRuntimeResult, StemRouting, etc.
  live_core.py       # Model path resolution + separation orchestration
  source_ingest.py   # Source-agnostic envelope (mp3/mic/video dispatch)
  mp3_ingest.py      # MP3 → PCM ingest
  mic_ingest.py      # Microphone capture (requires sounddevice)
  video_ingest.py    # Video → audio extraction
  stem_router.py     # Routes four stems to output paths

scripts/
  eval/              # UMX evaluation runner + metric aggregation
  export/            # ONNX export + TRT engine build scripts
  benchmark/         # Throughput, mic-latency, capstone evidence assembly
  live/              # Live separation CLI
  ui/                # Compare UI HTTP server
  verify/            # End-to-end slice verifiers (bash)

tests/
  eval/              # Metric aggregation + eval protocol guardrails
  runtime/           # Live runtime contracts, ingest, health, Demucs path
  benchmark/         # Timing schema, throughput, latency result validation
  export/            # ONNX export pipeline smoke tests
  integration/       # S06 evidence bundle integration test
  ui/                # Compare UI Playwright tests

ui/compare/          # Vanilla JS/HTML/CSS compare interface
fixtures/            # Audio/video fixtures for tests
data/musdb18/        # MUSDB18 evaluation dataset (test subset)
artifacts/           # Generated outputs (eval/, bench/, export/, live/)
configs/             # environment.lock.md — reproducibility assumptions
```

## Artifact Conventions

- All generated outputs go under `artifacts/` with sub-paths by stage.
- Live runs write to `artifacts/live/<run-id>/` with `live_runtime_result.json` + four WAV stems.
- Bench runs write to `artifacts/bench/s06-capstone-<id>/` and update `capstone_evidence_manifest.json`.
- JSON artifacts are schema-validated; `status` and `error_stage` fields are preserved even on failure.
- Existing engine files are reused unless `--force` is passed (build idempotency rule).

## Model Paths

- UMX (default): `artifacts/models/umx-live.pt`
- Demucs (supported): `artifacts/models/demucs-live.pt`
- Unsupported fallback sentinel: `artifacts/models/unsupported-live.pt`

## Testing Conventions

- Test files are named `test_*.py` under `tests/`.
- Mirror the `scripts/` / `live_runtime/` directory structure under `tests/`.
- Dry-run and contract tests must not require GPU or real model weights.
- UI tests use Playwright (`playwright==1.54.0` in dev extras).

## GPU / CI Notes

- GPU path is optional; all slice verifiers support `--dry-run` for CI.
- `trtexec` must be on `PATH` for TRT engine builds; CUDA and TensorRT versions must match the driver stack.
- ONNX export targets opset 17 (minimum 13); only the sample dimension may vary dynamically.
- See `configs/environment.lock.md` for full reproducibility assumptions.
