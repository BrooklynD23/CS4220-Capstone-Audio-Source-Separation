# Benchmark Scripts

Scripts under `scripts/benchmark/` measure throughput, latency, and compose the final capstone evidence bundle.

---

## `assemble_capstone_evidence.py`

**Purpose:** Reads all five phase artifacts (evaluation summary, live throughput, mic latency, live runtime, compare UI logs), validates each against its JSON schema, and writes a single `capstone_evidence_manifest.json` that preserves ordered phase status.

Phase order: `evaluation → throughput → mic_latency → live_runtime → compare_ui`

**Invocation:**

```bash
python scripts/benchmark/assemble_capstone_evidence.py [OPTIONS]
```

**Arguments:**

| Argument | Type | Default | Description |
|---|---|---|---|
| `--output` | path | `artifacts/bench/capstone_evidence_manifest.json` | Destination for the assembled manifest |
| `--evaluation-summary` | path | `artifacts/eval/summary-smoke.json` | Evaluation summary JSON |
| `--throughput-artifact` | path | `artifacts/bench/live-throughput/live_throughput_result.json` | Live throughput result JSON |
| `--mic-latency-artifact` | path | `artifacts/bench/mic-latency/mic_latency_result.json` | Mic latency result JSON |
| `--live-runtime-artifact` | path | auto-discovered via glob | Live runtime result JSON (`artifacts/live/s0*-*/live_runtime_result.json`) |
| `--compare-server-log` | path | auto-discovered via glob | Compare UI server log (`artifacts/live/s05-verify-server-*/server.log`) |
| `--compare-pytest-log` | path | auto-discovered via glob | Compare UI pytest log (`artifacts/live/s05-verify-pytest-*/pytest.log`) |

Auto-discovery selects the most recently modified file matching each glob pattern when an explicit path is not provided.

**Outputs:**

- `artifacts/bench/capstone_evidence_manifest.json` (or `--output` path) — manifest with top-level `status`, ordered `phases` array, `inputs` map, and `generated_at` timestamp.
- Exit code `0` when all phases report `status: ok`; `1` when any phase fails.

**Example:**

```bash
# Default paths — uses auto-discovered live and compare artifacts
python scripts/benchmark/assemble_capstone_evidence.py

# Explicit paths
python scripts/benchmark/assemble_capstone_evidence.py \
  --output artifacts/bench/capstone_evidence_manifest.json \
  --evaluation-summary artifacts/eval/summary-smoke.json \
  --throughput-artifact artifacts/bench/live-throughput/live_throughput_result.json \
  --mic-latency-artifact artifacts/bench/mic-latency/mic_latency_result.json \
  --live-runtime-artifact artifacts/live/s02-smoke-001/live_runtime_result.json \
  --compare-server-log artifacts/live/s05-verify-server-001/server.log \
  --compare-pytest-log artifacts/live/s05-verify-pytest-001/pytest.log
```

---

## `run_live_throughput.py`

**Purpose:** Launches `scripts/live/run_live_separation.py` as a subprocess, times the wall-clock duration, and writes a `live_throughput_result.json` artifact containing throughput metrics (ms/chunk, chunks/second). Validates the nested live runtime artifact via JSON schema.

**Invocation:**

```bash
python scripts/benchmark/run_live_throughput.py [OPTIONS]
```

**Arguments:**

| Argument | Type | Default | Description |
|---|---|---|---|
| `--input` | path | — | Source audio/video fixture path (required unless `--source-mode mic`) |
| `--output-dir` | path | `artifacts/bench/live-throughput` | Output directory for artifacts |
| `--artifact-path` | path | `<output-dir>/live_throughput_result.json` | Throughput result JSON path |
| `--live-artifact-path` | path | `<output-dir>/live_runtime_result.json` | Nested live runtime artifact path |
| `--source-mode` | `mp3\|video-audio\|mic` | `mp3` | Source mode forwarded to live CLI |
| `--device-requested` | `cpu\|gpu` | `cpu` | Requested device label |
| `--device-used` | `cpu\|gpu` | `cpu` | Actual device label |
| `--mode` | `smoke\|full` | `smoke` | Runtime mode forwarded to live CLI |
| `--chunk-duration-s` | float | `1.0` | Chunk duration forwarded to live CLI |
| `--sample-rate-hz` | int | `22050` | Target sample rate forwarded to live CLI |
| `--max-queue-depth` | int | `64` | Max queue depth forwarded to live CLI |
| `--decode-timeout-s` | float | `30.0` | Decode timeout forwarded to live CLI |
| `--model-path` | str | `artifacts/models/umx-live.pt` | Model path forwarded to live CLI |
| `--mic-backend` | `fake\|sounddevice` | `sounddevice` | Mic backend (mic mode only) |
| `--mic-device` | str | `default` | Mic device (mic mode only) |
| `--capture-duration-s` | float | `1.0` | Capture duration (mic mode only) |
| `--max-wall-clock-ms` | float | — | Optional wall-clock budget; error if exceeded |
| `--live-timeout-s` | float | `120.0` | Subprocess timeout for the live CLI |

**Outputs:**

- `artifacts/bench/live-throughput/live_throughput_result.json` — includes `wall_clock_ms`, `wall_clock_ms_per_chunk`, `throughput_chunks_per_second`, `status`, `phase`, and a nested `metadata` block.
- `artifacts/bench/live-throughput/live_runtime_result.json` — the live runtime artifact written by the subprocess.
- Exit code `0` on success; `1` on failure; `2` on config error.

**Example:**

```bash
python scripts/benchmark/run_live_throughput.py \
  --input fixtures/audio/demo_mix.mp3 \
  --output-dir artifacts/bench/live-throughput \
  --source-mode mp3 \
  --chunk-duration-s 1.0 \
  --max-wall-clock-ms 5000
```

---

## `run_mic_latency.py`

**Purpose:** Launches `scripts/live/run_live_separation.py` in mic mode, times the end-to-end capture latency, and writes a `mic_latency_result.json` artifact. Reads back `stft_ms` from the nested live runtime artifact to report the capture-stage latency.

**Invocation:**

```bash
python scripts/benchmark/run_mic_latency.py [OPTIONS]
```

**Arguments:**

| Argument | Type | Default | Description |
|---|---|---|---|
| `--output-dir` | path | `artifacts/bench/mic-latency` | Output directory for artifacts |
| `--artifact-path` | path | `<output-dir>/mic_latency_result.json` | Mic latency result JSON path |
| `--live-artifact-path` | path | `<output-dir>/live_runtime_result.json` | Nested live runtime artifact path |
| `--mic-backend` | `fake\|sounddevice` | `sounddevice` | Microphone capture backend |
| `--mic-device` | str | `default` | Microphone device identifier |
| `--capture-duration-s` | float | `1.0` | Capture window in seconds |
| `--device-requested` | `cpu\|gpu` | `cpu` | Requested runtime device |
| `--device-used` | `cpu\|gpu` | `cpu` | Actual runtime device |
| `--mode` | `smoke\|full` | `smoke` | Runtime mode |
| `--chunk-duration-s` | float | `1.0` | Chunk duration forwarded to live CLI |
| `--sample-rate-hz` | int | `22050` | Target sample rate |
| `--max-queue-depth` | int | `64` | Max queue depth |
| `--decode-timeout-s` | float | `30.0` | Capture/decode timeout |
| `--model-path` | str | `artifacts/models/umx-live.pt` | Model path |
| `--max-capture-latency-ms` | float | — | Optional latency budget; error if exceeded |
| `--live-timeout-s` | float | `120.0` | Subprocess timeout |

**Outputs:**

- `artifacts/bench/mic-latency/mic_latency_result.json` — includes `capture_latency_ms` (from `stft_ms`), `end_to_end_latency_ms`, `capture_backend_name`, `status`, `phase`.
- `artifacts/bench/mic-latency/live_runtime_result.json` — nested live runtime artifact.
- Exit code `0` on success; `1` on failure; `2` on config error.

**Example:**

```bash
# CI-safe with fake mic backend
python scripts/benchmark/run_mic_latency.py \
  --mic-backend fake \
  --capture-duration-s 1.0 \
  --output-dir artifacts/bench/mic-latency

# Real mic, budget check
python scripts/benchmark/run_mic_latency.py \
  --mic-backend sounddevice \
  --mic-device default \
  --max-capture-latency-ms 200
```

---

## `run_stage_timing.py`

**Purpose:** Reads a WAV fixture and runs a deterministic per-stage timing benchmark for STFT, infer, and ISTFT stages. In `--smoke-mode` the timings are proportional to preprocess time (no GPU needed). Writes a structured JSON timing artifact.

**Invocation:**

```bash
python scripts/benchmark/run_stage_timing.py --input <wav> --output <json> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `--input` | path | yes | — | Path to mono/stereo WAV input file |
| `--output` | path | yes | — | Output JSON artifact path |
| `--device` | `cpu\|gpu` | no | `cpu` | Requested benchmark device |
| `--smoke-mode` | flag | no | false | Use deterministic smoke timings (CI-safe, no GPU) |
| `--stages` | str | no | `stft,infer,istft` | Comma-delimited list of stages to time |
| `--prefer-monotonic` | flag | no | false | Force monotonic clock (tests fallback path) |
| `--preprocess-timeout-ms` | float | no | `5000.0` | Timeout for audio decode/preprocessing |

Valid stage names: `stft`, `infer`, `istft`.

If the fixture path ends with `fixtures/audio/10s_mix.wav` and the file does not exist, a synthetic 10-second 44100 Hz sine-wave WAV is auto-generated.

**Outputs:**

- JSON file at `--output` with fields: `status`, `stft_ms`, `infer_ms`, `istft_ms`, `total_ms`, `sample_rate_hz`, `chunk_duration_s`, `error_stage`, `error_message`, `timestamp`, `metadata`.
- Stdout: `wrote_timing_artifact: <path>` on success.
- Stderr: `benchmark_error[<stage>]: <message>` on failure.
- Exit code `0` on success; `1` on failure.

**Example:**

```bash
# Smoke timing from fixture (auto-generates WAV if missing)
python scripts/benchmark/run_stage_timing.py \
  --input fixtures/audio/10s_mix.wav \
  --output artifacts/bench/stage_timing.json \
  --smoke-mode

# Full stages, real WAV
python scripts/benchmark/run_stage_timing.py \
  --input fixtures/audio/demo_mix.wav \
  --output artifacts/bench/stage_timing_full.json \
  --stages stft,infer,istft \
  --device cpu
```
