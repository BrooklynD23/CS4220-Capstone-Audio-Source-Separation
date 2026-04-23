# Export Scripts

Scripts under `scripts/export/` handle ONNX export and TensorRT engine builds.

---

## `export_umx_onnx.py`

**Purpose:** Export the UMX model to ONNX format with deterministic metadata, TensorRT shape profiles, and a SHA-256 model hash. In `--dry-run` mode it writes a text placeholder instead of running torch export, making it safe for CI without GPU or real model weights.

**Invocation:**

```bash
python scripts/export/export_umx_onnx.py \
  --onnx-output <path.onnx> \
  --input-shape <batch,channels,samples> \
  --min-shape <batch,channels,samples> \
  --opt-shape <batch,channels,samples> \
  --max-shape <batch,channels,samples> \
  [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `--onnx-output` | path | yes | — | Destination `.onnx` file path |
| `--input-shape` | str | yes | — | Export input shape as `batch,channels,samples` |
| `--min-shape` | str | yes | — | TensorRT min profile as `batch,channels,samples` |
| `--opt-shape` | str | yes | — | TensorRT optimal profile as `batch,channels,samples` |
| `--max-shape` | str | yes | — | TensorRT max profile as `batch,channels,samples` |
| `--metadata-output` | path | no | `<onnx-output>.export.json` | Destination metadata JSON |
| `--traceback-output` | path | no | `<onnx-output>.traceback.log` | Destination traceback log on failure |
| `--model-path` | path | no | — | Local model checkpoint (`.pt`); if omitted, uses an identity module |
| `--model-source` | str | no | `open-unmix.umxhq` | Human-readable source string when `--model-path` is absent |
| `--opset` | int | no | `17` | ONNX opset version (minimum `13`) |
| `--export-timeout-s` | float | no | `180.0` | Export timeout in seconds |
| `--simulate-export-delay-s` | float | no | `0.0` | Testing hook: delay export to exercise timeout handling |
| `--dry-run` | flag | no | false | Skip torch export; write a text placeholder |

**Shape constraints:**

- All four shapes must have exactly 3 comma-delimited positive integers: `batch,channels,samples`.
- `min <= opt <= max` must hold for every dimension.
- Only the samples dimension may be dynamic: `batch` and `channels` must be identical across all four shapes.
- Opset must be `>= 13` for dynamic-shape export.

**Dynamic axis:**

The ONNX graph exports `input` and `output` tensors with a dynamic `samples` axis (dimension 2), labelled `"samples"`.

**Outputs:**

- `<onnx-output>` — the ONNX file (or dry-run placeholder).
- `<onnx-output>.export.json` (or `--metadata-output`) — metadata with `status`, `model_hash_sha256`, `input_shape`, `profile` (`min`/`opt`/`max`), `duration_ms`, `dry_run`, `opset`.
- `<onnx-output>.traceback.log` (or `--traceback-output`) — full traceback written on failure.
- Stdout: `export_ok: onnx=<path> metadata=<path>` on success.

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | Export succeeded |
| `1` | Unexpected export failure |
| `2` | Invalid shape profile or output path |
| `3` | Export timeout |

**Examples:**

```bash
# CI-safe dry run
python scripts/export/export_umx_onnx.py \
  --onnx-output artifacts/export/umx-smoke.onnx \
  --input-shape 1,2,44100 \
  --min-shape 1,2,22050 \
  --opt-shape 1,2,44100 \
  --max-shape 1,2,88200 \
  --dry-run

# Real export with local checkpoint
python scripts/export/export_umx_onnx.py \
  --onnx-output artifacts/export/umx-live.onnx \
  --model-path artifacts/models/umx-live.pt \
  --input-shape 1,2,44100 \
  --min-shape 1,2,22050 \
  --opt-shape 1,2,44100 \
  --max-shape 1,2,88200 \
  --opset 17
```

---

## `build_trt_engine.sh`

**Purpose:** Shell wrapper around `trtexec` that builds a TensorRT engine from an ONNX file. Requires `trtexec` on `PATH` and a compatible CUDA/TensorRT installation.

**Invocation:**

```bash
bash scripts/export/build_trt_engine.sh \
  --onnx <path.onnx> \
  --engine <path.engine> \
  --min-shape <1x2x22050> \
  --opt-shape <1x2x44100> \
  --max-shape <1x2x88200> \
  [--fp16] \
  [--timeout-s <seconds>] \
  [--dry-run]
```

Shape arguments use `NxCxS` notation (e.g. `1x2x44100`).

**Examples:**

```bash
# Dry run (CI-safe)
bash scripts/export/build_trt_engine.sh \
  --onnx artifacts/export/umx-smoke.onnx \
  --engine artifacts/bench/trt/umx-smoke.engine \
  --min-shape 1x2x22050 --opt-shape 1x2x44100 --max-shape 1x2x88200 \
  --dry-run

# GPU build with FP16
bash scripts/export/build_trt_engine.sh \
  --onnx artifacts/export/umx-smoke.onnx \
  --engine artifacts/bench/trt/umx-smoke.engine \
  --min-shape 1x2x22050 --opt-shape 1x2x44100 --max-shape 1x2x88200 \
  --fp16 --timeout-s 600
```

Existing engine files are reused unless `--force` is passed (idempotency rule).
