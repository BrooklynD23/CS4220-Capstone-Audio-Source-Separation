#!/usr/bin/env bash
set -euo pipefail

ARTIFACT_ROOT="artifacts/live"
DEFAULT_MODEL_PATH="$(python - <<'PY'
from live_runtime.live_core import DEFAULT_MODEL_PATH
print(DEFAULT_MODEL_PATH)
PY
)"
EXPECTED_STEMS=("vocals.wav" "drums.wav" "bass.wav" "other.wav")

mkdir -p "${ARTIFACT_ROOT}"
SMOKE_DIR="$(mktemp -d "${ARTIFACT_ROOT}/s02-smoke-XXXXXX")"
FAIL_DIR="$(mktemp -d "${ARTIFACT_ROOT}/s02-failure-XXXXXX")"
SMOKE_ARTIFACT="${SMOKE_DIR}/live_runtime_result.json"
FAIL_ARTIFACT="${FAIL_DIR}/live_runtime_result.json"

run_check() {
  local label="$1"
  shift
  local start end duration rc
  start="$(python - <<'PY'
import time
print(int(time.time() * 1000))
PY
)"
  if "$@"; then
    rc=0
  else
    rc=$?
  fi
  end="$(python - <<'PY'
import time
print(int(time.time() * 1000))
PY
)"
  duration=$((end - start))
  if [[ "$rc" -eq 0 ]]; then
    RESULTS+=("✅|$label|$rc|${duration}ms")
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    RESULTS+=("❌|$label|$rc|${duration}ms")
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
  return "$rc"
}

PASS_COUNT=0
FAIL_COUNT=0
RESULTS=()

assert_stem_contract() {
  local artifact_path="$1"
  local output_dir="$2"
  local expected_status="$3"
  local expected_health_state="$4"
  local expected_error_stage="$5"
  local expected_error_message_snippet="$6"
  local expected_stem_state="$7"
  python - <<'PY' "${artifact_path}" "${output_dir}" "${expected_status}" "${expected_health_state}" "${expected_error_stage}" "${expected_error_message_snippet}" "${expected_stem_state}" "${DEFAULT_MODEL_PATH}"
import json
from pathlib import Path
import sys

artifact_path = Path(sys.argv[1])
output_dir = Path(sys.argv[2])
expected_status = sys.argv[3]
expected_health_state = sys.argv[4]
expected_error_stage = None if sys.argv[5] == "null" else sys.argv[5]
expected_error_message_snippet = sys.argv[6]
expected_stem_state = sys.argv[7]
expected_model_path = sys.argv[8]
payload = json.loads(artifact_path.read_text(encoding="utf-8"))
actual_stems = sorted(path.name for path in output_dir.glob("*.wav"))
if expected_stem_state == "present":
    if actual_stems != ["bass.wav", "drums.wav", "other.wav", "vocals.wav"]:
        raise SystemExit(f"unexpected stem outputs for {output_dir.name}: {actual_stems}")
else:
    if actual_stems:
        raise SystemExit(f"unexpected stem outputs for {output_dir.name}: {actual_stems}")
stem_paths = payload.get("stem_paths", {})
if sorted(stem_paths.keys()) != ["bass", "drums", "other", "vocals"]:
    raise SystemExit(f"unexpected stem path keys for {output_dir.name}: {sorted(stem_paths.keys())}")
for stem_name in ["vocals", "drums", "bass", "other"]:
    expected_path = str(output_dir / f"{stem_name}.wav")
    if stem_paths.get(stem_name) != expected_path:
        raise SystemExit(f"unexpected stem path for {stem_name}: {stem_paths.get(stem_name)}")
if payload["status"] != expected_status:
    raise SystemExit(f"unexpected status for {output_dir.name}: {payload['status']}")
if payload["health_state"] != expected_health_state:
    raise SystemExit(f"unexpected health state for {output_dir.name}: {payload['health_state']}")
if payload["requested_model_path"] != expected_model_path:
    raise SystemExit(f"unexpected requested_model_path for {output_dir.name}: {payload['requested_model_path']}")
if payload["model_path"] != expected_model_path:
    raise SystemExit(f"unexpected model_path for {output_dir.name}: {payload['model_path']}")
if payload["fallback_applied"] is not False:
    raise SystemExit(f"unexpected fallback_applied for {output_dir.name}: {payload['fallback_applied']}")
if payload["error_stage"] != expected_error_stage:
    raise SystemExit(f"unexpected error_stage for {output_dir.name}: {payload['error_stage']}")
if expected_error_message_snippet and expected_error_message_snippet not in str(payload["error_message"]):
    raise SystemExit(f"unexpected error_message for {output_dir.name}: {payload['error_message']}")
print(f"{output_dir.name}: stem contract ok")
PY
}

echo "Running live smoke separation flow..."
python scripts/live/run_live_separation.py \
  --input fixtures/audio/demo_mix.mp3 \
  --output-dir "${SMOKE_DIR}" \
  --artifact-path "${SMOKE_ARTIFACT}"

python scripts/verify/validate_json.py \
  --schema artifacts/schema/live_runtime_result.schema.json \
  --input "${SMOKE_ARTIFACT}"

assert_stem_contract "${SMOKE_ARTIFACT}" "${SMOKE_DIR}" "ok" "healthy" "null" "" "present"

echo "Running missing-input failure-path check..."
if python scripts/live/run_live_separation.py \
  --input fixtures/audio/missing.mp3 \
  --output-dir "${FAIL_DIR}" \
  --artifact-path "${FAIL_ARTIFACT}"; then
  echo "expected missing-input run to fail" >&2
  exit 1
fi

python scripts/verify/validate_json.py \
  --schema artifacts/schema/live_runtime_result.schema.json \
  --input "${FAIL_ARTIFACT}"

assert_stem_contract "${FAIL_ARTIFACT}" "${FAIL_DIR}" "error" "degraded" "decode_failed" "missing.mp3" "absent"

if find "${FAIL_DIR}" -maxdepth 1 -name '*.wav' -print -quit | grep -q .; then
  echo "unexpected stem files left behind after failure" >&2
  exit 1
fi

echo
printf "%-3s | %-28s | %-8s | %-10s\n" "" "check" "exit" "duration"
printf "%s\n" "----+------------------------------+----------+-----------"
for row in "${RESULTS[@]}"; do
  IFS='|' read -r verdict label rc duration <<<"${row}"
  printf "%-3s | %-28s | %-8s | %-10s\n" "${verdict}" "${label}" "${rc}" "${duration}"
done

echo
echo "Verifier artifacts: ${ARTIFACT_ROOT}"

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
  echo "s02_check: FAIL (${FAIL_COUNT} failed, ${PASS_COUNT} passed)" >&2
  exit 1
fi

echo "s02_check: PASS (${PASS_COUNT} checks)"
