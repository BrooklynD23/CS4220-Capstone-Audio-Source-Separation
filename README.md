# CS4220 Capstone — Audio Source Separation

This repository contains the reproducible evaluation + timing harness for the M001/S01 UMX proof path.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## S01 Reproducibility Flow

Run the full slice verification contract (tests + smoke artifact generation + schema checks + export/build dry-run):

```bash
bash scripts/verify/s01_check.sh
```

The verifier writes artifacts under:

- `artifacts/eval/`
- `artifacts/bench/`
- `artifacts/export/`

## S02 Live Smoke Flow

Run the live MP3 → four-stem runtime contract check and its failure-path check with one command:

```bash
bash scripts/verify/s02_check.sh
```

The live smoke command writes:

- `artifacts/live/<run>/live_runtime_result.json`
- `artifacts/live/<run>/vocals.wav`
- `artifacts/live/<run>/drums.wav`
- `artifacts/live/<run>/bass.wav`
- `artifacts/live/<run>/other.wav`

The runtime artifact is schema-validated and preserves `status`, `error_stage`, timing fields, queue depth, drop count, and stem routing metadata even when the run fails.

For the M002 live-runtime contract, run:

```bash
bash scripts/verify/m002_s01_check.sh
```

That verifier exercises the supported Demucs request path at `artifacts/models/demucs-live.pt` and a separate unsupported fallback sentinel, so the slice contract distinguishes the first-class four-stem Demucs contract from visible fallback behavior.

## S06 Final Capstone Evidence Bundle

Run the final milestone verifier to compose the evaluation summary, live throughput benchmark, mic-latency benchmark, live-runtime proof, and compare-UI smoke evidence into one manifest:

```bash
bash scripts/verify/s06_check.sh
```

The final bundle writes fresh artifacts under `artifacts/bench/s06-capstone-*/` and produces the stable manifest at:

- `artifacts/bench/capstone_evidence_manifest.json`

The assembled manifest preserves the ordered phases `evaluation → throughput → mic_latency → live_runtime → compare_ui` and keeps phase-level failure states visible instead of collapsing them into a single success/failure bit.

## Local / Dry-Run Mode (CI-safe)

Use dry-run when GPU/TensorRT are unavailable:

```bash
python scripts/export/export_umx_onnx.py \
  --onnx-output artifacts/export/umx-smoke.onnx \
  --input-shape 1,2,44100 \
  --min-shape 1,2,22050 \
  --opt-shape 1,2,44100 \
  --max-shape 1,2,88200 \
  --dry-run

bash scripts/export/build_trt_engine.sh \
  --onnx artifacts/export/umx-smoke.onnx \
  --engine artifacts/bench/trt/umx-smoke.engine \
  --min-shape 1x2x22050 \
  --opt-shape 1x2x44100 \
  --max-shape 1x2x88200 \
  --dry-run
```

## GPU Build Mode

When TensorRT is installed and `trtexec` is available:

```bash
bash scripts/export/build_trt_engine.sh \
  --onnx artifacts/export/umx-smoke.onnx \
  --engine artifacts/bench/trt/umx-smoke.engine \
  --min-shape 1x2x22050 \
  --opt-shape 1x2x44100 \
  --max-shape 1x2x88200 \
  --fp16 \
  --timeout-s 600
```

For deterministic reruns and environment assumptions, see `configs/environment.lock.md`.
nment.lock.md`.
t.lock.md`.
