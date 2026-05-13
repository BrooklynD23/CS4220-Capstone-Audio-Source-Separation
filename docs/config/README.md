# Configuration Reference

This document covers all configuration surfaces for the CS4220 Audio Source Separation project: `pyproject.toml` project metadata and dependencies, pytest settings, the `configs/` directory, artifact JSON schemas, and the reproducibility contract.

---

## Table of Contents

1. [pyproject.toml — Project Metadata](#pyprojecttoml--project-metadata)
2. [Optional Extras](#optional-extras)
3. [pytest Configuration](#pytest-configuration)
4. [configs/ Directory](#configs-directory)
5. [Artifact JSON Schemas](#artifact-json-schemas)
   - [timing_result.schema.json](#timing_resultschemajson)
   - [eval_result.schema.json](#eval_resultschemajson)
   - [live_runtime_result.schema.json](#live_runtime_resultschemajson)
   - [live_throughput_result.schema.json](#live_throughput_resultschemajson)
   - [mic_latency_result.schema.json](#mic_latency_resultschemajson)
6. [Reproducibility Contract (environment.lock.md)](#reproducibility-contract-environmentlockmd)

---

## pyproject.toml — Project Metadata

File: `pyproject.toml`

### Build System

| Field | Value | Description |
|---|---|---|
| `requires` | `setuptools>=75.0.0`, `wheel>=0.44.0` | Minimum build tool versions required to build the package. |
| `build-backend` | `setuptools.build_meta` | PEP 517 build backend; uses setuptools, not poetry. |

### Project

| Field | Value | Description |
|---|---|---|
| `name` | `audio-source-separation-eval` | PyPI distribution name. |
| `version` | `0.1.0` | Current release version. |
| `description` | Reproducible evaluation and benchmarking harness for UMX proof workflows. | Short summary shown on PyPI and `pip show`. |
| `readme` | `README.md` | Long description source file. |
| `requires-python` | `>=3.10,<3.15` | Supported Python range; matches `[project]` in `pyproject.toml`. |

### Core Dependencies

These packages are installed by `pip install -e .` (or any equivalent install without extras).

| Package | Pinned Version | Purpose |
|---|---|---|
| `PyYAML` | `6.0.2` | YAML parsing for eval protocol config (`scripts/eval/eval_protocol.yaml`). |
| `jsonschema` | `4.23.0` | JSON Schema validation (Draft 2020-12) for all artifact outputs in `artifacts/schema/`. |
| `imageio-ffmpeg` | `0.6.0` | Bundled `ffmpeg` binary hooks for video audio extraction (`live_runtime/video_ingest.py`). |
| `numpy` | `>=1.24.0` | Numeric arrays for audio buffers and separation glue paths. |

Pinned packages (`PyYAML`, `jsonschema`, `imageio-ffmpeg`) match the reproducibility contract in `configs/environment.lock.md`; `numpy` follows the lower bound from `[project.dependencies]`.

---

## Optional Extras

Install extras alongside the core package:

```bash
# Development tooling (tests, coverage, browser automation)
pip install -e .[dev]

# Microphone capture support (requires PortAudio system library)
pip install -e .[mic]

# Both at once
pip install -e .[dev,mic]
```

### `dev` extra

Installs testing and browser automation tools needed for the full test suite.

| Package | Pinned Version | Purpose |
|---|---|---|
| `pytest` | `8.3.5` | Test runner. Minimum version required by `[tool.pytest.ini_options]` is `8.0`. |
| `pytest-cov` | `7.1.0` | Coverage plugin for `--cov` flag; default pytest options enforce `--cov=live_runtime` / `--cov=scripts` and `--cov-fail-under=80`. |
| `playwright` | `1.54.0` | Headless browser for Playwright-based compare UI tests under `tests/ui/`. |

### `mic` extra

Installs hardware I/O support for real microphone capture.

| Package | Pinned Version | Purpose |
|---|---|---|
| `sounddevice` | `0.5.1` | PortAudio Python bindings. Enables `live_runtime/mic_ingest.py` on real audio hardware. Requires PortAudio to be installed at the OS level (`apt install portaudio19-dev` on Debian/Ubuntu). |

The `mic` extra is intentionally separate so CI environments without PortAudio can install `[dev]` cleanly. At runtime, `mic_ingest.py` imports `sounddevice` lazily, so the package will not crash on import if `sounddevice` is absent.

### `gpu_launcher` and `gpu` extras

CUDA PyTorch wheels are installed from the PyTorch wheel index (see `launch.py` / root README); `pip install -e .[gpu_launcher]` pulls Open-Unmix, Demucs, and plotting/audio deps **without** PyAudio. `pip install -e .[gpu]` adds `torch`, `torchaudio`, PyAudio, and the same model stack for full GPU separation and mic-capable demos.

---

## pytest Configuration

Section: `[tool.pytest.ini_options]` in `pyproject.toml`

| Option | Value | Effect |
|---|---|---|
| `minversion` | `"8.0"` | pytest will exit with an error if the installed version is older than 8.0. |
| `addopts` | `"-ra --strict-config --strict-markers --cov=live_runtime --cov=scripts --cov-fail-under=80"` | Default CLI flags appended to every invocation (see below). |
| `testpaths` | `["tests"]` | Only the `tests/` directory is scanned for test files; the project root and `live_runtime/` are not walked. |

### `addopts` flags explained

| Flag | Description |
|---|---|
| `-ra` | Print a short summary of all non-passing tests (errors, failures, skips, xfails) at the end of the run. |
| `--strict-config` | Treat unknown `[tool.pytest.ini_options]` keys as errors, preventing silent misconfiguration. |
| `--strict-markers` | Any `@pytest.mark.*` decorator that is not registered in the config raises an error, preventing marker typos from silently skipping tests. |
| `--cov=live_runtime` / `--cov=scripts` | Collect coverage for the runtime package and `scripts/` tree (mirrors `[tool.coverage.run]` omit list for heavy GPU/export paths). |
| `--cov-fail-under=80` | Fail the run if total coverage falls below 80%. |

### Common invocations

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=live_runtime --cov=scripts -v

# Run a single test file
pytest tests/runtime/test_contracts.py -v

# Run only tests matching a keyword
pytest -k "ingest" -v
```

---

## configs/ Directory

```
configs/
└── environment.lock.md   # Reproducibility assumptions for eval/benchmark/export
```

Currently the only file is `environment.lock.md`, which documents the Python toolchain, model versions, GPU/CUDA assumptions, and constraints that must hold for the slice verifiers to produce reproducible results. See [Reproducibility Contract](#reproducibility-contract-environmentlockmd) below.

---

## Artifact JSON Schemas

All schemas live in `artifacts/schema/` and use **JSON Schema Draft 2020-12**. They are validated at runtime via `jsonschema` (see core dependency above). Every artifact object sets `"additionalProperties": false`, so unrecognised fields cause validation failures.

### timing_result.schema.json

Title: `TimingResult` — per-chunk timing breakdown produced by the live inference pipeline.

**Top-level fields**

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `input` | string | yes | minLength 1 | Path or identifier of the audio input. |
| `sample_rate_hz` | integer | yes | 8000–48000 | Sample rate of the processed audio. |
| `chunk_duration_s` | number | yes | (0, 30] | Duration in seconds of the processed chunk. |
| `stft_ms` | number | yes | ≥ 0 | Milliseconds spent computing the Short-Time Fourier Transform. |
| `infer_ms` | number | yes | ≥ 0 | Milliseconds spent on model inference. |
| `istft_ms` | number | yes | ≥ 0 | Milliseconds spent on the Inverse STFT. |
| `total_ms` | number | yes | ≥ 0 | Total pipeline wall-clock time in milliseconds. |
| `status` | string | yes | `"ok"` \| `"error"` | Overall result status. |
| `error_stage` | string \| null | yes | minLength 1 or null | Name of the pipeline stage that failed; null on success. |
| `error_message` | string \| null | yes | minLength 1 or null | Human-readable failure description; null on success. |
| `timestamp` | string | yes | minLength 1 | ISO 8601 timestamp of when the artifact was generated. |
| `metadata` | object | yes | see below | Execution context. |

**`metadata` sub-fields**

| Field | Type | Constraints | Description |
|---|---|---|---|
| `device_requested` | string | `"cpu"` \| `"gpu"` | Device the caller requested. |
| `device_used` | string | `"cpu"` \| `"gpu"` | Device actually used (may differ if GPU unavailable). |
| `mode` | string | `"smoke"` \| `"full"` | Run mode: smoke is a short CI-safe run; full processes complete input. |
| `clock_source` | string | minLength 1 | Name of the timing clock used (e.g. `perf_counter`). |
| `clock_fallback` | boolean | — | True if the primary clock was unavailable and a fallback was used. |
| `samples_processed` | integer | ≥ 0 | Number of audio samples processed. |
| `channels` | integer | 0–8 | Number of audio channels. |
| `sample_width_bytes` | integer | 0–8 | Bytes per audio sample. |
| `stages` | array of string | minItems 1; items: `"stft"`, `"infer"`, `"istft"` | Ordered list of pipeline stages that ran. |

---

### eval_result.schema.json

Title: `EvalResult` — UMX evaluation summary written by `scripts/eval/`.

**Top-level fields**

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `protocol_version` | string | yes | minLength 1 | Version string from `eval_protocol.yaml` (e.g. `"1.0"`). |
| `dataset` | string | yes | minLength 1 | Dataset identifier (e.g. `"musdb18-test"`). |
| `track_count` | integer | yes | ≥ 0 | Number of tracks evaluated. |
| `vocal_sdr_median_db` | number | yes | — | Median Signal-to-Distortion Ratio across tracks, in dB. |
| `threshold_db` | number | yes | — | Minimum SDR threshold required to pass. |
| `pass` | boolean | yes | — | True if `vocal_sdr_median_db >= threshold_db`. |
| `passes_threshold` | boolean | yes | — | Alias for `pass`; both are required. |
| `status` | string | yes | `"ok"` \| `"error"` | Overall result status. |
| `error_stage` | string \| null | yes | minLength 1 or null | Pipeline stage that failed; null on success. |
| `generated_at` | string | yes | minLength 1 | ISO 8601 generation timestamp. |
| `notes` | string | no | — | Optional free-text annotation. |
| `timing_ms` | object | no | see below | Optional per-stage timing. |

**`timing_ms` sub-fields** (all optional)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `load_ms` | number | ≥ 0 | Time to load the model, in ms. |
| `separate_ms` | number | ≥ 0 | Time to run source separation, in ms. |
| `aggregate_ms` | number | ≥ 0 | Time to aggregate metrics across tracks, in ms. |

---

### live_runtime_result.schema.json

Title: `LiveRuntimeResult` — full artifact written to `artifacts/live/<run-id>/live_runtime_result.json` for each live separation run.

**Top-level fields**

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `source` | object | yes | see below | Describes the audio input source. |
| `input` | string | yes | minLength 1 | File path or device reference. |
| `sample_rate_hz` | integer | yes | 8000–48000 | Sample rate. |
| `chunk_duration_s` | number | yes | (0, 30] | Duration of the processed chunk. |
| `chunk_index` | integer | yes | ≥ 0 | Zero-based index of this chunk in the stream. |
| `stft_ms` | number | yes | ≥ 0 | STFT time, ms. |
| `infer_ms` | number | yes | ≥ 0 | Inference time, ms. |
| `istft_ms` | number | yes | ≥ 0 | ISTFT time, ms. |
| `total_ms` | number | yes | ≥ 0 | Total pipeline time, ms. |
| `status` | string | yes | `"ok"` \| `"error"` | Run status. |
| `error_stage` | string \| null | yes | minLength 1 or null | Failed stage name; null on success. |
| `error_message` | string \| null | yes | minLength 1 or null | Error detail; null on success. |
| `timestamp` | string | yes | minLength 1 | ISO 8601 timestamp. |
| `health_state` | string | yes | `"healthy"` \| `"degraded"` \| `"fallback"` | Runtime health classification. |
| `health_reason` | string | yes | minLength 1 | Human-readable explanation of the health state. |
| `requested_model_path` | string | yes | minLength 1 | Model path the caller requested. |
| `fallback_applied` | boolean | yes | — | True if a fallback model was used instead of the requested one. |
| `queue_depth` | integer | yes | ≥ 0 | Number of chunks currently queued. |
| `drop_count` | integer | yes | ≥ 0 | Number of chunks dropped due to queue overflow. |
| `model_path` | string | yes | minLength 1 | Path to the model actually used. |
| `stem_paths` | object | yes | see below | Paths to each output WAV stem. |
| `metadata` | object | yes | see below | Execution context (same shape as TimingResult). |

**`source` sub-fields**

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `kind` | string | yes | `"mp3"` \| `"video_audio"` \| `"mic"` | Input source type. |
| `reference` | string | yes | minLength 1 | Source path or device identifier. |
| `metadata` | object | no | — | Optional source-specific metadata. |

**`stem_paths` sub-fields** (all required)

| Field | Type | Description |
|---|---|---|
| `vocals` | string | Path to the vocals WAV output. |
| `drums` | string | Path to the drums WAV output. |
| `bass` | string | Path to the bass WAV output. |
| `other` | string | Path to the other/accompaniment WAV output. |

**`metadata` sub-fields** — same shape as `TimingResult.metadata` (see above).

---

### live_throughput_result.schema.json

Title: `LiveThroughputResult` — throughput benchmark written by `scripts/benchmark/`.

**Top-level fields**

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `input` | string | yes | minLength 1 | Source audio path. |
| `output_dir` | string | yes | minLength 1 | Directory where live artifacts were written. |
| `live_artifact_path` | string | yes | minLength 1 | Path to the underlying `live_runtime_result.json`. |
| `chunk_duration_s` | number | yes | (0, 30] | Chunk size used. |
| `wall_clock_ms` | number | yes | ≥ 0 | Total observed wall-clock time, ms. |
| `wall_clock_ms_per_chunk` | number | yes | ≥ 0 | Average wall-clock time per chunk, ms. |
| `throughput_chunks_per_second` | number | yes | ≥ 0 | Measured throughput rate. |
| `device_requested` | string | yes | `"cpu"` \| `"gpu"` | Requested compute device. |
| `device_used` | string | yes | `"cpu"` \| `"gpu"` | Actual compute device. |
| `source_mode` | string | yes | `"mp3"` \| `"video-audio"` \| `"mic"` | Input source type (note: `video-audio` uses a hyphen, unlike `live_runtime_result`). |
| `status` | string | yes | `"ok"` \| `"error"` | Benchmark status. |
| `phase` | string | yes | minLength 1 | Phase label (e.g. `"throughput"`). |
| `error_stage` | string \| null | yes | minLength 1 or null | Failed stage; null on success. |
| `error_message` | string \| null | yes | minLength 1 or null | Error detail; null on success. |
| `stderr` | string | yes | — | Captured stderr from the live CLI subprocess. |
| `live_cli_exit_code` | integer \| null | yes | — | Exit code of the live CLI process; null if not started. |
| `live_runtime_status` | string \| null | yes | `"ok"` \| `"error"` or null | Status field from the inner live artifact. |
| `live_runtime_error_stage` | string \| null | yes | minLength 1 or null | Error stage from the inner live artifact. |
| `live_runtime_error_message` | string \| null | yes | minLength 1 or null | Error message from the inner live artifact. |
| `timestamp` | string | yes | minLength 1 | ISO 8601 timestamp. |
| `metadata` | object | yes | see below | Benchmark run context. |

**`metadata` sub-fields**

| Field | Type | Constraints | Description |
|---|---|---|---|
| `clock_source` | string | minLength 1 | Timing clock identifier. |
| `live_timeout_s` | number | ≥ 0 | Subprocess timeout in seconds. |
| `max_wall_clock_ms` | number \| null | ≥ 0 or null | Maximum allowed wall-clock ms; null means no cap. |
| `live_command` | array of string | minItems 1 | The live CLI command invocation as a list of arguments. |
| `device_requested` | string | `"cpu"` \| `"gpu"` | Requested device. |
| `device_used` | string | `"cpu"` \| `"gpu"` | Actual device. |
| `source_mode` | string | `"mp3"` \| `"video-audio"` \| `"mic"` | Input source type. |

---

### mic_latency_result.schema.json

Title: `MicLatencyResult` — microphone end-to-end latency benchmark.

**Top-level fields**

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `input` | string | yes | minLength 1 | Mic device identifier or placeholder. |
| `output_dir` | string | yes | minLength 1 | Directory for live artifacts. |
| `live_artifact_path` | string | yes | minLength 1 | Path to the inner live artifact. |
| `capture_backend_name` | string | yes | `"fake"` \| `"sounddevice"` | Backend used for mic capture. `"fake"` is the CI-safe stub. |
| `capture_duration_s` | number | yes | (0, 30] | How long the mic capture ran, in seconds. |
| `capture_latency_ms` | number \| null | yes | ≥ 0 or null | Latency reported by the capture backend; null if unavailable. |
| `end_to_end_latency_ms` | number | yes | ≥ 0 | Total measured latency from capture to stem output, ms. |
| `device_requested` | string | yes | `"cpu"` \| `"gpu"` | Requested compute device. |
| `device_used` | string | yes | `"cpu"` \| `"gpu"` | Actual compute device. |
| `status` | string | yes | `"ok"` \| `"error"` | Benchmark status. |
| `phase` | string | yes | minLength 1 | Phase label (e.g. `"mic_latency"`). |
| `error_stage` | string \| null | yes | minLength 1 or null | Failed stage; null on success. |
| `error_message` | string \| null | yes | minLength 1 or null | Error detail; null on success. |
| `stderr` | string | yes | — | Captured stderr from the live CLI subprocess. |
| `live_cli_exit_code` | integer \| null | yes | — | Exit code of the live CLI process. |
| `live_runtime_status` | string \| null | yes | `"ok"` \| `"error"` or null | Status from the inner live artifact. |
| `live_runtime_error_stage` | string \| null | yes | minLength 1 or null | Error stage from inner artifact. |
| `live_runtime_error_message` | string \| null | yes | minLength 1 or null | Error message from inner artifact. |
| `timestamp` | string | yes | minLength 1 | ISO 8601 timestamp. |
| `metadata` | object | yes | see below | Benchmark run context. |

**`metadata` sub-fields**

| Field | Type | Constraints | Description |
|---|---|---|---|
| `clock_source` | string | minLength 1 | Timing clock identifier. |
| `live_timeout_s` | number | ≥ 0 | Subprocess timeout, seconds. |
| `max_capture_latency_ms` | number \| null | ≥ 0 or null | Latency threshold for pass/fail; null means no cap. |
| `live_command` | array of string | minItems 1 | Live CLI invocation arguments. |
| `device_requested` | string | `"cpu"` \| `"gpu"` | Requested device. |
| `device_used` | string | `"cpu"` \| `"gpu"` | Actual device. |
| `capture_backend_name` | string | `"fake"` \| `"sounddevice"` | Capture backend. |
| `capture_duration_s` | number | (0, 30] | Duration of mic capture. |
| `source_mode` | string | const `"mic"` | Always `"mic"` for this schema. |
| `model_path` | string | minLength 1 | Path to the model used in the latency run. |

---

## Reproducibility Contract (environment.lock.md)

File: `configs/environment.lock.md`

This file is the authoritative statement of assumptions that must hold for the slice verifiers (`scripts/verify/`) to produce reproducible results. Deviating from these assumptions may produce artifacts that are not comparable across runs.

### Python Toolchain

| Assumption | Value |
|---|---|
| Python version range | `>=3.10,<3.15` |
| Dependency lock source | `pyproject.toml` |
| `PyYAML` | `6.0.2` |
| `jsonschema` | `4.23.0` |
| `imageio-ffmpeg` | `0.6.0` |
| `numpy` | `>=1.24.0` (see `pyproject.toml`) |
| `pytest` | `8.3.5` (dev extra) |
| `pytest-cov` | `7.1.0` (dev extra) |

### Model and Runtime Versions

| Item | Value |
|---|---|
| Primary model (M001/S01) | UMX (`open-unmix.umxhq`), path `artifacts/models/umx-live.pt` |
| M002 supported path | Demucs at `artifacts/models/demucs-live.pt` |
| M002 fallback sentinel | `artifacts/models/unsupported-live.pt` |
| Eval protocol lock | `scripts/eval/eval_protocol.yaml`, `protocol_version: 1.0` |
| ONNX opset target | `17` (minimum supported: `13`) |
| TRT build tool | `trtexec` from TensorRT 8.x/10.x matching your CUDA driver |

### GPU / CUDA Assumptions

- GPU is **optional**. All slice verifiers support `--dry-run` for CI use.
- When GPU is in use: CUDA runtime and NVIDIA driver must be compatible with the installed TensorRT binaries.
- `trtexec` must be on `PATH` or provided via `--trtexec`.

### Shape and Build Constraints

| Constraint | Detail |
|---|---|
| Input shape format | `batch,channels,samples` for the export script |
| TensorRT profile format | `BxCxS` for the build script |
| Dynamic dimension | Only the sample dimension may vary; batch and channels are fixed |
| Build idempotency | Existing engine files are reused unless `--force` is passed |
| Timing-cache path | Must be explicit or default to `artifacts/bench/trt/timing.cache`; empty path is rejected |

### Logging and Redaction Rules

- Do **not** store API tokens, dataset credentials, or local secret values in artifacts.
- Host fingerprinting is limited to tool/runtime versions and GPU model strings.
- Failure artifacts must include `status`, `error_stage`, and timestamps for observability.

### Verification Commands

```bash
# Full S01 slice verifier
bash scripts/verify/s01_check.sh

# ONNX export dry-run (CI-safe)
python scripts/export/export_umx_onnx.py \
  --onnx-output artifacts/export/umx-smoke.onnx \
  --input-shape 1,2,44100 \
  --min-shape 1,2,22050 \
  --opt-shape 1,2,44100 \
  --max-shape 1,2,88200 \
  --dry-run

# TRT build dry-run (CI-safe)
bash scripts/export/build_trt_engine.sh \
  --onnx artifacts/export/umx-smoke.onnx \
  --engine artifacts/bench/trt/umx-smoke.engine \
  --min-shape 1x2x22050 \
  --opt-shape 1x2x44100 \
  --max-shape 1x2x88200 \
  --dry-run
```
