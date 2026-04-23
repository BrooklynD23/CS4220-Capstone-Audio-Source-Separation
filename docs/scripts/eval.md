# Eval Scripts

Scripts under `scripts/eval/` run UMX evaluation and aggregate per-track metrics.

---

## `run_umx_eval.py`

**Purpose:** Discover track directories under a MUSDB18 dataset root, (optionally) run model inference per track, and write per-track metrics artifacts. In `--dry-run` mode it emits deterministic SDR values without any GPU or real model weights.

**Invocation:**

```bash
python scripts/eval/run_umx_eval.py \
  --protocol scripts/eval/eval_protocol.yaml \
  --dataset-root data/musdb18 \
  --output artifacts/eval/run-001 \
  [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `--protocol` | path | yes | — | Path to evaluation protocol YAML |
| `--dataset-root` | path | yes | — | MUSDB18 dataset root directory |
| `--output` | path | yes | — | Output directory for per-track artifacts |
| `--max-tracks` | int | no | `1` | Maximum number of tracks to process |
| `--dry-run` | flag | no | false | Skip model inference; emit deterministic artifacts |
| `--model-timeout-s` | float | no | `30.0` | Maximum time allowed for model initialization |
| `--simulate-model-load-failure` | flag | no | false | Testing hook: force model load failure |
| `--simulate-model-load-delay-s` | float | no | `0.0` | Testing hook: delay model load (timeout test) |

**Protocol YAML (`scripts/eval/eval_protocol.yaml`):**

```yaml
protocol_version: 1.0
dataset:
  name: musdb18
  split: test
aggregation:
  threshold_db: 5.0
```

The `split` field determines which subdirectory under `--dataset-root` is scanned for track directories.

**Outputs:**

- `<output>/run_result.json` — top-level run status, `track_count`, list of `track_artifacts` paths, `environment` fingerprint.
- `<output>/track_000.json`, `track_001.json`, … — per-track metrics with `track_name`, `targets.vocals.sdr`, stage timings (`stft_ms`, `infer_ms`, `istft_ms`, `total_ms`), `status`.

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unexpected error |
| `2` | Dataset not found |
| `3` | Model load timeout |
| `4` | Model load failed |
| `5` | Dataset access / track discovery error |

**Example:**

```bash
# CI-safe dry run against test subset (1 track)
python scripts/eval/run_umx_eval.py \
  --protocol scripts/eval/eval_protocol.yaml \
  --dataset-root data/musdb18 \
  --output artifacts/eval/run-smoke \
  --max-tracks 1 \
  --dry-run

# Run 5 tracks (requires real model weights)
python scripts/eval/run_umx_eval.py \
  --protocol scripts/eval/eval_protocol.yaml \
  --dataset-root data/musdb18 \
  --output artifacts/eval/run-full \
  --max-tracks 5
```

---

## `aggregate_metrics.py`

**Purpose:** Read per-track metrics (from a file or directory of `track_*.json` files), extract the `targets.vocals.sdr` value from each, compute the median, compare it against a `threshold_db`, and write a summary JSON verdict.

**Invocation:**

```bash
python scripts/eval/aggregate_metrics.py \
  --input <path> \
  --output <path> \
  [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `--input` | path | yes | — | Metrics file or directory containing `track_*.json` |
| `--output` | path | yes | — | Output summary JSON path |
| `--protocol` | path | no | `scripts/eval/eval_protocol.yaml` | Protocol YAML for default threshold + metadata |
| `--threshold-db` | float | no | protocol value (`5.0`) | Override threshold in dB |

**Input formats accepted:**

- A single JSON file that is a list of track result objects.
- A single JSON file that is an object with a `track_results` list (inline `protocol_version`, `dataset`, `threshold_db` are used if present).
- A directory containing `track_*.json` files (sorted by name). If a `run_result.json` is present, its `status` is checked before loading tracks.

**Outputs:**

- JSON file at `--output` with fields:
  - `protocol_version`, `dataset` — from protocol or inline metadata
  - `track_count` — number of tracks aggregated
  - `vocal_sdr_median_db` — median SDR across tracks
  - `threshold_db` — comparison threshold
  - `passes_threshold` / `pass` — boolean verdict
  - `status` — `"ok"` or `"error"`
  - `error_stage`, `generated_at`
- Stdout: `Wrote summary: <path>` on success.
- Exit code `0` on success; `1` on any error.

**Example:**

```bash
# Aggregate from a run directory
python scripts/eval/aggregate_metrics.py \
  --input artifacts/eval/run-smoke \
  --output artifacts/eval/summary-smoke.json

# Override threshold
python scripts/eval/aggregate_metrics.py \
  --input artifacts/eval/run-smoke \
  --output artifacts/eval/summary-smoke.json \
  --threshold-db 3.0

# From a single metrics file
python scripts/eval/aggregate_metrics.py \
  --input artifacts/eval/all_tracks.json \
  --output artifacts/eval/summary.json
```
