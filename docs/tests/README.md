# Test Suite Documentation

This document covers the test organisation for the CS4220 Audio Source Separation capstone project.
All tests live under `tests/` and are run with pytest.

---

## Directory Tree

```
tests/
├── benchmark/
│   ├── test_timing_schema.py          — Stage-timing benchmark: schema validation, error paths, validator CLI
│   ├── test_live_throughput_result.py — Live throughput benchmark: wall-clock measurement, schema, failure phases
│   └── test_mic_latency_result.py     — Mic-latency benchmark: capture latency, fake backend, failure phases
├── eval/
│   ├── test_metric_aggregation.py     — SDR metric aggregation logic and eval runner error paths
│   └── test_protocol_guardrails.py    — Eval protocol YAML validation, immutable-defaults enforcement, schema versions
├── export/
│   └── test_export_pipeline_scripts.py — ONNX export dry-run and TRT engine build shell-script contracts
├── integration/
│   └── test_s06_evidence_bundle.py    — S06 capstone evidence assembler: phase ordering, failure preservation
├── runtime/
│   ├── test_live_runtime_contract.py  — JSON schema contract for live_runtime_result artifacts
│   ├── test_live_runtime_demucs.py    — Demucs model path resolution and fallback telemetry
│   ├── test_live_runtime_health.py    — Model path resolution, degraded/fallback health states, schema rejection
│   ├── test_live_runtime_ingest.py    — MP3 ingest chunks, stem writer, backpressure, schema validation
│   ├── test_live_runtime_smoke.py     — Live CLI end-to-end: all source modes, degraded, fallback, error paths
│   └── test_live_runtime_sources.py   — Source descriptors for mp3/video/mic modes, CLI argument parsing
└── ui/
    └── test_compare_ui.py             — Playwright E2E: compare UI mode switching, artifact loading, validation errors
```

---

## Coverage Map

| Test file | Primary module(s) exercised |
|---|---|
| `tests/benchmark/test_timing_schema.py` | `scripts/benchmark/run_stage_timing.py`, `scripts/verify/validate_json.py` |
| `tests/benchmark/test_live_throughput_result.py` | `scripts/benchmark/run_live_throughput.py` |
| `tests/benchmark/test_mic_latency_result.py` | `scripts/benchmark/run_mic_latency.py` |
| `tests/eval/test_metric_aggregation.py` | `scripts/eval/aggregate_metrics.py`, `scripts/eval/run_umx_eval.py` |
| `tests/eval/test_protocol_guardrails.py` | `scripts/eval/eval_protocol.yaml`, `artifacts/schema/eval_result.schema.json`, `artifacts/schema/timing_result.schema.json` |
| `tests/export/test_export_pipeline_scripts.py` | `scripts/export/export_umx_onnx.py`, `scripts/export/build_trt_engine.sh` |
| `tests/integration/test_s06_evidence_bundle.py` | `scripts/benchmark/assemble_capstone_evidence.py` |
| `tests/runtime/test_live_runtime_contract.py` | `live_runtime/contracts.py` |
| `tests/runtime/test_live_runtime_demucs.py` | `live_runtime/live_core.py` (`DEMUCS_MODEL_PATH`, `resolve_live_model_path`), `live_runtime/contracts.py` |
| `tests/runtime/test_live_runtime_health.py` | `live_runtime/live_core.py` (`resolve_live_model_path`, `build_live_runtime_result`), `live_runtime/contracts.py`, `live_runtime/source_ingest.py` |
| `tests/runtime/test_live_runtime_ingest.py` | `live_runtime/source_ingest.py`, `live_runtime/mp3_ingest.py`, `live_runtime/live_core.py`, `live_runtime/stem_router.py` |
| `tests/runtime/test_live_runtime_smoke.py` | `scripts/live/run_live_separation.py` (CLI), all ingest modules, `live_runtime/contracts.py` |
| `tests/runtime/test_live_runtime_sources.py` | `live_runtime/source_ingest.py`, `live_runtime/mic_ingest.py`, `live_runtime/video_ingest.py`, `live_runtime/mp3_ingest.py`, `scripts/live/run_live_separation.py` |
| `tests/ui/test_compare_ui.py` | `ui/compare/` (Playwright E2E against served static assets) |

---

## Fixture Inventory

### `conftest.py` fixtures

There are no top-level or subdirectory `conftest.py` files. Fixtures are defined locally inside individual test modules.

| Fixture | Defined in | Scope | Description |
|---|---|---|---|
| `throughput_module` | `tests/benchmark/test_live_throughput_result.py` | `function` | Loads `scripts/benchmark/run_live_throughput.py` as a module via `importlib` for in-process testing |
| `mic_latency_module` | `tests/benchmark/test_mic_latency_result.py` | `function` | Loads `scripts/benchmark/run_mic_latency.py` as a module via `importlib` for in-process testing |
| `bundle_dir` | `tests/integration/test_s06_evidence_bundle.py` | `function` | Returns `tmp_path / "bundle"` as a clean staging area for assembler inputs |
| `compare_server` | `tests/ui/test_compare_ui.py` | `module` | Spins up a `ThreadingHTTPServer` on a random port serving the project root; honours `COMPARE_DEMO_BASE_URL` env var to reuse an external server |

### Static test fixtures

| Path | Used by | Description |
|---|---|---|
| `fixtures/audio/demo_mix.mp3` | `tests/runtime/`, `tests/benchmark/` | MP3 fixture (~10 s stereo mix) for ingest and CLI tests |
| `fixtures/audio/10s_mix.wav` | `tests/benchmark/test_timing_schema.py` | WAV fixture for stage-timing benchmark |
| `fixtures/video/demo_mix.mp4` | `tests/runtime/test_live_runtime_smoke.py`, `test_live_runtime_sources.py` | MP4 fixture for video-audio ingest path |
| `tests/fixtures/eval/sample_track_metrics.json` | `tests/eval/test_metric_aggregation.py` | MUSDB18-style per-track SDR results |
| `tests/fixtures/eval/sample_summary_input.json` | `tests/eval/test_metric_aggregation.py` | Pre-aggregated summary payload for threshold checks |
| `tests/fixtures/ui/compare/healthy.json` | `tests/ui/test_compare_ui.py` | Valid `live_runtime_result` artifact with `health_state: healthy` |
| `tests/fixtures/ui/compare/degraded.json` | `tests/ui/test_compare_ui.py` | Artifact with `health_state: degraded`, non-zero queue/drop counts |
| `tests/fixtures/ui/compare/fallback.json` | `tests/ui/test_compare_ui.py` | Artifact with `health_state: fallback`, `fallback_applied: true` |
| `tests/fixtures/ui/compare/malformed.json` | `tests/ui/test_compare_ui.py` | Invalid artifact (legacy two-stem shape) for rejection testing |
| `tests/fixtures/ui/compare/video_audio.json` | `tests/ui/test_compare_ui.py` | Artifact produced from a `video_audio` source kind |

---

## Test Patterns

### Schema validation

Many tests construct a JSON payload, serialise it to a dict, and pass it through `validate_live_runtime_result(payload, schema=schema)` from `live_runtime.contracts`. The pattern verifies both the happy path (schema accepts the payload) and rejection paths (missing required fields, wrong types, wrong enum values, wrong `stem_paths` shape). This guarantees that every field added to the schema is tested for presence, type, and content.

The `artifacts/schema/` directory holds Draft 2020-12 JSON Schema files. Tests load them with `jsonschema.Draft202012Validator` and assert on `$schema` version strings to prevent silent schema-version drift.

### Contract testing

`tests/runtime/test_live_runtime_contract.py` treats the schema as the contract. Parametrised test cases drive the three valid `health_state` values (`healthy`, `degraded`, `fallback`) through the full roundtrip and assert that each field in the contract survives serialisation. Negative cases confirm that removing or mistyping any required field raises `jsonschema.ValidationError` with the offending field name in the error message.

`tests/eval/test_protocol_guardrails.py` applies the same idea to the eval protocol YAML: it loads the real `eval_protocol.yaml`, applies overrides, and asserts that immutable defaults (`sample_rate_hz`, `aggregation.metric`, etc.) cannot be mutated.

### Smoke testing

Smoke tests invoke real CLI entry points via `subprocess.run` with `--dry-run` or `--smoke-mode` flags so that the full argument-parse → processing → artifact-write pipeline runs without requiring GPU weights or real audio hardware. `tests/runtime/test_live_runtime_smoke.py` is the canonical smoke suite: it exercises MP3, video-audio, and mic (via `--mic-backend fake`) modes and asserts on artifact content and WAV stem presence.

`tests/export/test_export_pipeline_scripts.py` uses ONNX export `--dry-run` and TRT build `--dry-run` to verify CLI argument validation and idempotency without a GPU.

### Integration testing

`tests/integration/test_s06_evidence_bundle.py` tests the capstone evidence assembler end-to-end. It writes all five phase input files to a `tmp_path`, invokes the assembler CLI, and verifies the output manifest's `phase_order`, per-phase `status`, and top-level `error_stage`. Failure-preservation tests confirm that a failing throughput phase is surfaced in the manifest rather than collapsed into a single boolean.

### Monkeypatching for determinism

`tests/benchmark/test_live_throughput_result.py` and `tests/benchmark/test_mic_latency_result.py` load benchmark scripts as Python modules via `importlib` and use `monkeypatch.setattr` to swap out `subprocess.run` and `time.perf_counter`. This lets tests control wall-clock values precisely and exercise every error branch (missing artifact, malformed JSON, nonzero exit, budget exceeded) without running real subprocesses.

### Playwright E2E

`tests/ui/test_compare_ui.py` uses `playwright.sync_api` to drive a headless Chromium browser against a locally served copy of `ui/compare/`. Tests load JSON fixtures via the file-upload input, assert on `data-testid` attributes for all rendered UI state, and verify that invalid artifacts are rejected without replacing the previously loaded state. The `compare_server` fixture is module-scoped to share one HTTP server across all UI tests.

---

## How to Run the Suite

### Full suite with coverage

```bash
# Install dev dependencies first
pip install -e .[dev]

# Run all tests
pytest

# Run with coverage report
pytest --cov=live_runtime --cov=scripts -v
```

### Subset by directory

```bash
pytest tests/runtime/          # live runtime contracts and ingest
pytest tests/benchmark/        # timing, throughput, latency
pytest tests/eval/             # metric aggregation and protocol
pytest tests/export/           # ONNX/TRT export pipeline
pytest tests/integration/      # S06 evidence bundle
pytest tests/ui/               # Playwright compare UI (requires Playwright browsers)
```

### Install Playwright browsers (UI tests only)

```bash
python -m playwright install chromium
```

UI tests are skipped automatically if `playwright` is not importable (`pytest.importorskip`).

### Slice verifier scripts

The bash verifiers in `scripts/verify/` exercise the same contracts as the pytest suite but through the full shell pipeline:

```bash
bash scripts/verify/s01_check.sh       # ONNX export + schema
bash scripts/verify/s02_check.sh       # Live MP3 → four-stem
bash scripts/verify/m002_s01_check.sh  # Demucs live-runtime contract
bash scripts/verify/s06_check.sh       # Final capstone evidence bundle
```

---

## Testing Philosophy

**Schema-first.** Every JSON artifact produced by the runtime has a corresponding Draft 2020-12 schema in `artifacts/schema/`. Tests treat the schema as the source of truth and validate both the production code and the test payloads against it. Adding a field without updating the schema causes a test failure.

**Failure states are first-class.** Tests assert on `status`, `error_stage`, and `health_state` fields in error scenarios with the same rigour as in the happy path. The artifact format is designed so that partial results (e.g., stems written before a queue overload) are preserved and observable.

**No GPU required in CI.** All tests that touch the export or inference pipeline use `--dry-run` or `--smoke-mode` flags. Mic-capture tests use the `FakeMicCaptureBackend`. This makes the full pytest suite runnable on any machine without CUDA or PortAudio.

**Contract isolation over mocking.** Where possible, tests call the real ingest and routing functions with small audio fixtures rather than mocking them. Mocks are reserved for `subprocess` and `time.perf_counter` in benchmark tests where controlling wall-clock values is essential.

**Idempotency.** Re-running the same CLI command into the same output directory must produce a valid artifact. `test_live_cli_can_rerun_into_the_same_output_dir` and the TRT build idempotency test encode this requirement.
