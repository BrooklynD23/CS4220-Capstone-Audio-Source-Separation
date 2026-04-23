# Verify Scripts

Scripts under `scripts/verify/` validate JSON artifacts and run end-to-end slice verifiers.

---

## `validate_json.py`

**Purpose:** Validate a JSON payload file against a JSON Schema (Draft 2020-12). Prints all validation errors with their JSON Pointer paths. Used by the slice verifier shell scripts to confirm that generated artifacts conform to their schemas.

**Invocation:**

```bash
python scripts/verify/validate_json.py \
  --schema <schema.json> \
  --input <payload.json>
```

**Arguments:**

| Argument | Type | Required | Description |
|---|---|---|---|
| `--schema` | path | yes | Path to JSON Schema file (Draft 2020-12) |
| `--input` | path | yes | Path to the JSON payload to validate |

**Outputs:**

On success:
- Stdout: `validation_ok`
- Exit code `0`

On validation failure:
- Stderr: `validation_failed: <N> error(s)`
- Stderr: one line per error: `- path=<json-pointer> message=<message>`
- Exit code `1`

On input/schema error:
- Stderr: descriptive error message
- Exit code `2` (file not found), `3` (invalid JSON or schema error), `4` (unexpected error)

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | Validation passed |
| `1` | Payload failed schema validation |
| `2` | Input or schema file not found |
| `3` | Malformed JSON or invalid schema |
| `4` | Unexpected internal error |

**Examples:**

```bash
# Validate a live runtime artifact
python scripts/verify/validate_json.py \
  --schema artifacts/schema/live_runtime_result.schema.json \
  --input artifacts/live/smoke-001/live_runtime_result.json

# Validate an eval summary
python scripts/verify/validate_json.py \
  --schema artifacts/schema/eval_result.schema.json \
  --input artifacts/eval/summary-smoke.json

# Validate a throughput result
python scripts/verify/validate_json.py \
  --schema artifacts/schema/live_throughput_result.schema.json \
  --input artifacts/bench/live-throughput/live_throughput_result.json
```

---

## Slice Verifier Shell Scripts

The bash scripts in `scripts/verify/` compose multiple steps into end-to-end slice contracts. They are not Python entry points but are documented here for completeness.

| Script | Purpose |
|---|---|
| `s01_check.sh` | ONNX export + schema validation (S01 reproducibility contract) |
| `s02_check.sh` | Live MP3 → four-stem separation contract |
| `m002_s01_check.sh` | Demucs live-runtime contract (supported path + unsupported fallback) |
| `s06_check.sh` | Final capstone evidence bundle assembly |

**Usage:**

```bash
bash scripts/verify/s01_check.sh
bash scripts/verify/s02_check.sh
bash scripts/verify/m002_s01_check.sh
bash scripts/verify/s06_check.sh
```

All verifiers support `--dry-run` for CI environments without GPU or real model weights.
