# Live Scripts

Scripts under `scripts/live/` run the live audio source separation pipeline.

---

## `run_live_separation.py`

**Purpose:** Run the live smoke separation flow for MP3, video-audio, or microphone input. Writes a schema-validated `live_runtime_result.json` artifact and four WAV stem files (`vocals.wav`, `drums.wav`, `bass.wav`, `other.wav`). Even on failure it writes a partial artifact preserving `status`, `error_stage`, `error_message`, `health_state`, timing fields, `queue_depth`, and `drop_count`.

The JSON artifact is written atomically (temp file + rename) so partial writes cannot corrupt the output.

**Invocation:**

```bash
python scripts/live/run_live_separation.py [OPTIONS]
```

**Arguments:**

| Argument | Type | Default | Description |
|---|---|---|---|
| `--source-mode` | `mp3\|video-audio\|mic` | `mp3` | Source type for live ingest |
| `--input` | path | mode fixture | Source file path (MP3 or video); defaults to `fixtures/audio/demo_mix.mp3` or `fixtures/video/demo_mix.mp4` |
| `--output-dir` | path | `artifacts/live/smoke` | Directory for stem WAVs and the artifact |
| `--artifact-path` | path | `<output-dir>/live_runtime_result.json` | JSON artifact path |
| `--sample-rate-hz` | int | `22050` | Target sample rate for decode and output stems |
| `--chunk-duration-s` | float | `0.5` | Chunk duration for the live ingest core |
| `--decode-timeout-s` | float | `30.0` | Timeout for source decode or mic capture |
| `--max-queue-depth` | int | `64` | Queue depth threshold recorded in the artifact |
| `--device-requested` | `cpu\|gpu` | `cpu` | Requested runtime device (recorded in artifact) |
| `--device-used` | `cpu\|gpu` | `cpu` | Actual runtime device (recorded in artifact) |
| `--mode` | `smoke\|full` | `smoke` | Runtime mode recorded in the artifact |
| `--model-path` | str | `artifacts/models/umx-live.pt` | Model path recorded in the artifact |
| `--mic-backend` | `fake\|sounddevice` | `sounddevice` | Mic capture backend (`--source-mode mic` only) |
| `--mic-device` | str | `default` | Mic device identifier (`--source-mode mic` only) |
| `--capture-duration-s` | float | `1.0` | Mic capture window in seconds (`--source-mode mic` only) |

**Model path resolution:**

The model path is resolved via `live_runtime.live_core.resolve_live_model_path`. If the specified path does not exist, a fallback sentinel is applied and `fallback_applied: true` is recorded in the artifact. See [Model Paths in CLAUDE.md](../../CLAUDE.md) for the path conventions.

**Outputs:**

On success:
- `<output-dir>/live_runtime_result.json` — full `LiveRuntimeResult` schema
- `<output-dir>/vocals.wav`
- `<output-dir>/drums.wav`
- `<output-dir>/bass.wav`
- `<output-dir>/other.wav`
- Stdout: `live_runtime_artifact: <path>` and `live_stems: <paths>`

On failure:
- `<output-dir>/live_runtime_result.json` — partial artifact with `status: error`
- Stderr: `live_runtime_failed[<stage>]: <message>` or `live_cli_failed: <message>`

Exit code `0` on success; `1` on any failure.

**Examples:**

```bash
# MP3 source (default fixture)
python scripts/live/run_live_separation.py \
  --source-mode mp3 \
  --output-dir artifacts/live/smoke-001

# Specific MP3 file
python scripts/live/run_live_separation.py \
  --source-mode mp3 \
  --input fixtures/audio/demo_mix.mp3 \
  --output-dir artifacts/live/smoke-002 \
  --sample-rate-hz 44100

# Video source
python scripts/live/run_live_separation.py \
  --source-mode video-audio \
  --input fixtures/video/demo_mix.mp4 \
  --output-dir artifacts/live/video-001

# Microphone (CI-safe fake backend)
python scripts/live/run_live_separation.py \
  --source-mode mic \
  --mic-backend fake \
  --capture-duration-s 2.0 \
  --output-dir artifacts/live/mic-001

# Real microphone
python scripts/live/run_live_separation.py \
  --source-mode mic \
  --mic-backend sounddevice \
  --mic-device default \
  --capture-duration-s 5.0 \
  --output-dir artifacts/live/mic-live
```
