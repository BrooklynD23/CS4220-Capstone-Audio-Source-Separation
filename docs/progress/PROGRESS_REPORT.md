# CS4220 Capstone — Intermediate Progress Report

**Project Title:** Reproducible Evaluation and Benchmarking Harness for Audio Source Separation  
**Team:** Danny (BrooklynD23)  
**Date:** April 30, 2026

---

## 1. Project Idea

Audio source separation is the task of decomposing a mixed audio signal into its constituent stems—typically **vocals, drums, bass, and other**. The practical challenge is not merely running a pre-trained model, but building a *production-grade*, *reproducible* inference pipeline that can be validated end-to-end under controlled conditions and extended to real-time sources (MP3 files, live microphone, video audio).

This project builds an evaluation and benchmarking harness for two established open-source separation models:

- **Open-Unmix (UMX / `umxhq`)** — a STFT-domain recurrent network that separates four stems from stereo audio.
- **Demucs** — a time-domain convolutional model targeting the same four stems.

The harness validates the full inference chain from raw audio ingest through model execution to structured artifact emission, and additionally exercises the ONNX export path and (optionally) TensorRT engine compilation for GPU acceleration. A lightweight browser-based compare UI allows side-by-side listening of separated stems.

---

## 2. Implementation Progress

### 2.1 Pipeline Architecture

The pipeline is organized into three layers:

```
Source Ingest  →  Separation Core  →  Stem Routing + Artifact Emission
  (MP3 / Mic /      (UMX or Demucs       (vocals / drums / bass / other
   Video)            STFT → infer          WAVs + JSON manifest)
                     → iSTFT)
```

**`live_runtime/` package** (importable runtime library, ~1,400 lines):

| Module | Responsibility |
|---|---|
| `contracts.py` | Frozen dataclasses: `LiveRuntimeResult`, `StemRouting`, `HealthTelemetry`, `StageTimings`, etc. |
| `live_core.py` | Model-path resolution, separation orchestration, health/fallback logic |
| `source_ingest.py` | Source-agnostic dispatch (mp3 / mic / video) |
| `mp3_ingest.py` | MP3 → PCM chunked ingest |
| `mic_ingest.py` | Microphone capture (PortAudio / fake backend) |
| `video_ingest.py` | Video → audio extraction |
| `stem_router.py` | Routes four stems to output paths |

**`scripts/` directory** (~3,200 lines across eval, export, benchmark, live, UI, verify):

- `scripts/eval/run_umx_eval.py` — drives MUSDB18 evaluation per track, emits per-track JSON
- `scripts/eval/aggregate_metrics.py` — aggregates per-track SDR into a summary JSON
- `scripts/export/export_umx_onnx.py` — exports UMX weights to ONNX (opset 17) with shape profile
- `scripts/export/build_trt_engine.sh` — wraps `trtexec` to compile a TensorRT engine from the ONNX
- `scripts/benchmark/run_live_throughput.py` — measures wall-clock throughput (chunks/second) on MP3 input
- `scripts/benchmark/run_mic_latency.py` — measures end-to-end latency from mic capture to stem output
- `scripts/benchmark/run_stage_timing.py` — profiles STFT / infer / iSTFT stage latencies individually
- `scripts/benchmark/assemble_capstone_evidence.py` — assembles ordered evidence manifest (S06)
- `scripts/live/run_live_separation.py` — CLI entry point for live separation from any source
- `scripts/ui/serve_compare_demo.py` — serves the browser compare UI
- `scripts/verify/s01_check.sh` … `s06_check.sh` — end-to-end slice verifiers

**`ui/compare/`** — Vanilla JS/HTML/CSS compare interface with stem playback controls.

### 2.2 Evaluation Results (MUSDB18 Smoke Subset)

Evaluation is run against a 1-track dry-run subset of MUSDB18. Full dataset evaluation requires model weights; the harness is validated against the smoke protocol to confirm metric aggregation and threshold logic are correct.

| Metric | Value |
|---|---|
| Dataset | MUSDB18 (smoke subset, 1 track) |
| Vocal SDR (median) | **5.0 dB** |
| Threshold (pass criterion) | ≥ 5.0 dB |
| Protocol version | 1.0 |
| Status | **PASS** |

The eval pipeline enforces a locked protocol (`scripts/eval/eval_protocol.yaml`) that guards against threshold changes after the run starts. Immutable defaults (dataset name, protocol version) are enforced by a guardrail layer tested by `tests/eval/test_protocol_guardrails.py`.

### 2.3 Throughput Benchmark (CPU, MP3 Source)

Throughput is measured as chunks separated per second. Chunks are 1-second segments at 22,050 Hz sample rate.

| Metric | Value |
|---|---|
| Device | CPU (no GPU available) |
| Source mode | MP3 |
| Chunk duration | 1.0 s |
| Sample rate | 22,050 Hz |
| **Throughput** | **0.76 chunks/second** |
| Wall clock per chunk | **1,314.9 ms** |
| Live CLI exit code | 0 (success) |

At 0.76× real-time on CPU, the pipeline processes audio at below real-time speed, which is expected for an unoptimized CPU path. The TensorRT path (GPU, FP16) is expected to exceed real-time; see Section 4.

### 2.4 Stage Timing Breakdown (CPU, smoke run)

The live runtime records per-stage latencies on each processed chunk:

| Stage | Latency (ms) |
|---|---|
| STFT | 23.1 ms |
| UMX Inference | 0.6 ms (smoke model) |
| iSTFT | 0.15 ms |
| **Total (pipeline)** | **23.1 ms** |

The STFT dominates total per-chunk latency on CPU; inference itself is negligible in smoke mode. With real UMX weights, inference dominates on CPU (expected: 200–400 ms/chunk).

### 2.5 Mic Latency Benchmark

The mic-latency pipeline is validated with a fake audio backend (CI-safe; no physical microphone required).

| Metric | Value |
|---|---|
| Capture backend | fake (fixture) |
| Capture duration | 1.0 s |
| Capture latency | **0.066 ms** |
| **End-to-end latency** | **1,353.9 ms** |
| Live runtime status | ok |

End-to-end latency includes capture + model inference + stem writing. On GPU with FP16, this is expected to drop below 500 ms.

### 2.6 ONNX Export

The ONNX export pipeline targets opset 17 with a dynamic sample-dimension profile:

| Parameter | Value |
|---|---|
| Model | `open-unmix.umxhq` |
| Opset | 17 |
| Input shape | (1, 2, 44100) |
| Profile (min / opt / max) | (1,2,22050) / (1,2,44100) / (1,2,88200) |
| Export duration | 6.9 ms (dry-run) |
| SHA-256 (exported ONNX) | `5264529e…` |
| Status | ok |

The export script also emits a traceback log on failure, enabling post-mortem diagnosis without re-running.

### 2.7 Compare UI and End-to-End Tests

A browser-based compare UI (`ui/compare/`) allows A/B listening of separated stems. It is served by `scripts/ui/serve_compare_demo.py` and smoke-tested by a Playwright suite.

| Item | Value |
|---|---|
| UI tests (Playwright) | **5/5 passing** |
| Test duration | 48.8 s |
| Server requests verified | GET /ui/compare/ (HTML + JS + CSS) |

### 2.8 Test Suite Summary

The project has a comprehensive test suite covering unit, integration, and UI layers:

| Test Category | Tests |
|---|---|
| Benchmark (throughput, latency, timing) | 27 |
| Evaluation (metric aggregation, protocol guardrails) | 15 |
| Runtime (live contract, ingest, health, Demucs) | 40+ |
| Export (ONNX pipeline smoke) | 20+ |
| Integration (S06 evidence bundle) | 15+ |
| UI (Playwright compare UI) | 5 |
| **Total** | **132 passing** |

All 132 tests pass on the current codebase with zero failures (`pytest`, ~79 seconds).

---

## 3. Challenges and Changes from Proposal

### 3.1 GPU / TensorRT Path Is Deferred

**Challenge:** The development environment (WSL2 on Windows) does not have a GPU or TensorRT installation available. All benchmarks above are CPU-only.

**Change from proposal:** The proposal assumed GPU-accelerated inference as the primary performance story. The harness fully supports the TensorRT path (the build scripts and dry-run mode are implemented and tested), but measured GPU results are pending access to a CUDA-capable machine.

**Mitigation:** The TensorRT build is validated in dry-run mode; all other pipeline stages (ingest, ONNX export, live separation, schema validation, UI) are fully tested and produce real artifacts on CPU.

### 3.2 MUSDB18 Evaluation Is Smoke-Only

**Challenge:** Full MUSDB18 evaluation requires downloading the dataset (~20 GB) and loading real UMX model weights (not present in the repository for size reasons).

**Change from proposal:** The metric evaluation uses a 1-track smoke subset that validates the aggregation logic, threshold enforcement, and artifact schema—but does not produce published SDR numbers on the full test set.

**Mitigation:** The eval harness is designed so that swapping in the real dataset root produces the full run without code changes. The vocal SDR threshold (5.0 dB) is consistent with published UMX results on MUSDB18 (~6–7 dB on the full test set).

### 3.3 Two-Model Support Added (Demucs)

**Addition beyond proposal:** The M002 milestone added a validated Demucs live-runtime contract alongside UMX. The verifier (`scripts/verify/m002_s01_check.sh`) distinguishes the four-stem Demucs path from the UMX path and explicitly tests fallback behavior when an unsupported model is requested. This was not in the original proposal scope.

---

## 4. Next Steps

| Priority | Task |
|---|---|
| High | Run full MUSDB18 eval with real UMX weights; report median SDR across all test tracks |
| High | Access a GPU machine, build TensorRT FP16 engine, and benchmark GPU throughput and latency |
| High | Measure real microphone end-to-end latency (PortAudio hardware backend) |
| Medium | Extend the compare UI to support file upload and display waveform visualizations |
| Medium | Add Demucs to the full eval loop and report SDR comparison (UMX vs Demucs) |
| Low | Package the harness for one-command reproducibility (`docker compose up`) |
| Low | Add a CI workflow (GitHub Actions) that runs the full slice verifier suite on push |

The most impactful remaining work is the GPU benchmark and full-dataset evaluation, which will replace the smoke-mode numbers with real performance claims suitable for the final submission.

---

## Appendix: Key Artifacts

| Artifact | Path |
|---|---|
| Capstone evidence manifest | `artifacts/bench/capstone_evidence_manifest.json` |
| ONNX export metadata | `artifacts/export/umx-smoke.export.json` |
| Evaluation summary | `artifacts/eval/summary-smoke.json` |
| Throughput result | `artifacts/bench/s06-capstone-yWHKIE/throughput/live_throughput_result.json` |
| Mic latency result | `artifacts/bench/s06-capstone-yWHKIE/mic-latency/mic_latency_result.json` |
| Live runtime result | `artifacts/bench/s06-capstone-yWHKIE/live/live_runtime_result.json` |
| Eval protocol | `scripts/eval/eval_protocol.yaml` |
| Environment lock | `configs/environment.lock.md` |
