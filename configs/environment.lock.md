# Environment Lock (M001/S01)

This document captures the reproducibility assumptions for evaluation, timing, and ONNX→TensorRT build workflows.

## Python Toolchain

- Python: `>=3.10,<3.13`
- Dependency lock source: `pyproject.toml`
- Required pinned packages:
  - `PyYAML==6.0.2`
  - `jsonschema==4.23.0`
  - `pytest==8.3.5` (dev)
  - `pytest-cov==6.0.0` (dev)

## Model and Runtime Versions

- Primary model path for this milestone: UMX (`open-unmix.umxhq`) as defined by decision D001.
- M002 live-runtime contract: the supported Demucs request path is `artifacts/models/demucs-live.pt`; the verifier uses `artifacts/models/unsupported-live.pt` as the explicit fallback sentinel.
- Eval protocol lock: `scripts/eval/eval_protocol.yaml` (`protocol_version: 1.0`).
- ONNX export runbook target opset: `17` (minimum supported in this runbook: `13`).
- TensorRT build tool expected: `trtexec` from a TensorRT 8.x/10.x install that matches your CUDA driver stack.

## GPU / CUDA / TensorRT Assumptions

- GPU path is optional for S01 contract checks; dry-run paths are the CI-safe baseline.
- When using GPU build mode:
  - CUDA runtime and NVIDIA driver must be compatible with the installed TensorRT binaries.
  - `trtexec` must be available via `PATH` or passed explicitly via `--trtexec`.
- Shared-resource risk at scale (Q6): repeated engine rebuilds are disk/compile-time bound before memory-bound.

## Reproducibility Constraints

- Keep shape/profile explicit for export/build commands:
  - Input shape format: `batch,channels,samples` for export script.
  - TensorRT profile format: `BxCxS` for build script.
- Dynamic behavior constraint: only the sample dimension may vary; batch/channels remain fixed.
- Build idempotency rule: existing engine artifacts are reused unless `--force` is passed.
- Timing-cache path must be explicit or use the default `artifacts/bench/trt/timing.cache`; empty path is rejected.

## Verification Commands

- End-to-end slice verifier:
  - `bash scripts/verify/s01_check.sh`
- Direct export/build smoke checks:
  - `python scripts/export/export_umx_onnx.py --onnx-output artifacts/export/umx-smoke.onnx --input-shape 1,2,44100 --min-shape 1,2,22050 --opt-shape 1,2,44100 --max-shape 1,2,88200 --dry-run`
  - `bash scripts/export/build_trt_engine.sh --onnx artifacts/export/umx-smoke.onnx --engine artifacts/bench/trt/umx-smoke.engine --min-shape 1x2x22050 --opt-shape 1x2x44100 --max-shape 1x2x88200 --dry-run`

## Redaction and Logging Guardrails

- Do **not** store API tokens, dataset credentials, or local secret values in artifacts.
- Allowed host fingerprinting for this slice is limited to tool/runtime versions and GPU model strings.
- Script failure artifacts should include `status`, `error_stage`, and timestamps for observability.

## Monitoring Targets

- Eval: `vocal_sdr_median_db >= 5.0`; `passes_threshold: true`.
- Throughput: `chunks_per_sec >= 0.5`.
- Mic end-to-end latency: `<= 2000ms`.
- Live runtime health: `healthy`; `degraded` or `fallback` requires investigation.
