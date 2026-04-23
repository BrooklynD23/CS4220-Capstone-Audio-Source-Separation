#!/usr/bin/env bash
set -u

PASS_COUNT=0
FAIL_COUNT=0
RESULTS=()

now_ms() {
  python - <<'PY'
import time
print(int(time.time() * 1000))
PY
}

run_check() {
  local label="$1"
  shift

  local start end duration rc
  start="$(now_ms)"
  "$@"
  rc=$?
  end="$(now_ms)"
  duration=$((end - start))

  if [[ "$rc" -eq 0 ]]; then
    PASS_COUNT=$((PASS_COUNT + 1))
    RESULTS+=("✅|$label|$rc|${duration}ms")
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    RESULTS+=("❌|$label|$rc|${duration}ms")
  fi
}

check_environment_lock_sections() {
  python - <<'PY'
from pathlib import Path
import sys

path = Path("configs/environment.lock.md")
required = [
    "## Python Toolchain",
    "## Model and Runtime Versions",
    "## GPU / CUDA / TensorRT Assumptions",
    "## Reproducibility Constraints",
    "## Verification Commands",
]

if not path.exists():
    print(f"missing environment lock doc: {path}", file=sys.stderr)
    raise SystemExit(1)

text = path.read_text(encoding="utf-8")
missing = [section for section in required if section not in text]
if missing:
    print("missing required section(s): " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)

print("environment.lock sections: ok")
PY
}

mkdir -p artifacts/eval/smoke-run artifacts/bench artifacts/export artifacts/bench/trt
mkdir -p artifacts/eval/.tmp_musdb/test/TrackSmoke01

run_check "environment-lock-sections" check_environment_lock_sections
run_check "pytest protocol guardrails" pytest tests/eval/test_protocol_guardrails.py -q
run_check "pytest metric aggregation" pytest tests/eval/test_metric_aggregation.py -q
run_check "pytest timing schema" pytest tests/benchmark/test_timing_schema.py -q
run_check "pytest export pipeline scripts" pytest tests/export/test_export_pipeline_scripts.py -q

run_check "eval smoke dry-run" \
  python scripts/eval/run_umx_eval.py \
    --protocol scripts/eval/eval_protocol.yaml \
    --dataset-root artifacts/eval/.tmp_musdb \
    --output artifacts/eval/smoke-run \
    --max-tracks 1 \
    --dry-run

run_check "aggregate eval summary" \
  python scripts/eval/aggregate_metrics.py \
    --input artifacts/eval/smoke-run \
    --output artifacts/eval/summary-smoke.json

run_check "timing smoke" \
  python scripts/benchmark/run_stage_timing.py \
    --input fixtures/audio/10s_mix.wav \
    --output artifacts/bench/timing-smoke.json \
    --device cpu \
    --smoke-mode

run_check "validate timing schema" \
  python scripts/verify/validate_json.py \
    --schema artifacts/schema/timing_result.schema.json \
    --input artifacts/bench/timing-smoke.json

run_check "validate eval schema" \
  python scripts/verify/validate_json.py \
    --schema artifacts/schema/eval_result.schema.json \
    --input artifacts/eval/summary-smoke.json

run_check "export onnx dry-run" \
  python scripts/export/export_umx_onnx.py \
    --onnx-output artifacts/export/umx-smoke.onnx \
    --metadata-output artifacts/export/umx-smoke.export.json \
    --model-source open-unmix.umxhq \
    --input-shape 1,2,44100 \
    --min-shape 1,2,22050 \
    --opt-shape 1,2,44100 \
    --max-shape 1,2,88200 \
    --dry-run

run_check "trt build dry-run" \
  bash scripts/export/build_trt_engine.sh \
    --onnx artifacts/export/umx-smoke.onnx \
    --engine artifacts/bench/trt/umx-smoke.engine \
    --min-shape 1x2x22050 \
    --opt-shape 1x2x44100 \
    --max-shape 1x2x88200 \
    --timing-cache artifacts/bench/trt/umx-smoke.timing.cache \
    --dry-run

echo
printf "%-3s | %-36s | %-8s | %-10s\n" "" "check" "exit" "duration"
printf "%s\n" "----+--------------------------------------+----------+-----------"
for row in "${RESULTS[@]}"; do
  IFS='|' read -r verdict label rc duration <<<"$row"
  printf "%-3s | %-36s | %-8s | %-10s\n" "$verdict" "$label" "$rc" "$duration"
done

echo
echo "Evidence paths:"
echo "- artifacts/eval/smoke-run/run_result.json"
echo "- artifacts/eval/summary-smoke.json"
echo "- artifacts/bench/timing-smoke.json"
echo "- artifacts/export/umx-smoke.export.json"
echo "- artifacts/bench/trt/build_log.json"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo "s01_check: FAIL (${FAIL_COUNT} failed, ${PASS_COUNT} passed)" >&2
  exit 1
fi

echo "s01_check: PASS (${PASS_COUNT} checks)"
