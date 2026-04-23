#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="."
CLI_SCRIPT="${PROJECT_ROOT}/scripts/live/run_live_separation.py"
SCHEMA_PATH="${PROJECT_ROOT}/artifacts/schema/live_runtime_result.schema.json"
VALIDATE_JSON="${PROJECT_ROOT}/scripts/verify/validate_json.py"
MP3_FIXTURE="fixtures/audio/demo_mix.mp3"
DEMUCS_MODEL_PATH="artifacts/models/demucs-live.pt"
UNSUPPORTED_MODEL_PATH="artifacts/models/unsupported-live.pt"
DEFAULT_MODEL_PATH="$(python - <<'PY'
from live_runtime.live_core import DEFAULT_MODEL_PATH
print(DEFAULT_MODEL_PATH)
PY
)"
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/live"

mkdir -p "${ARTIFACT_ROOT}"
VERIFY_ROOT="$(mktemp -d "${ARTIFACT_ROOT}/m002-s01-XXXXXX")"

PASS_COUNT=0
FAIL_COUNT=0
RESULTS=()
LAST_SUCCESSFUL_CASE="none"

now_ms() {
  python - <<'PY'
import time
print(int(time.time() * 1000))
PY
}

record_result() {
  local verdict="$1"
  local label="$2"
  local rc="$3"
  local duration="$4"
  RESULTS+=("${verdict}|${label}|${rc}|${duration}ms")
  if [[ "${verdict}" == "✅" ]]; then
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

fail_case() {
  local label="$1"
  local message="$2"
  local rc="${3:-1}"
  echo "m002_s01_check[${label}]: ${message}" >&2
  echo "Verifier artifacts: ${VERIFY_ROOT}" >&2
  echo "Last successful case: ${LAST_SUCCESSFUL_CASE}" >&2
  exit "${rc}"
}

run_cli_case() {
  local label="$1"
  shift
  local case_dir="${VERIFY_ROOT}/${label}"
  local artifact_path="${case_dir}/live_runtime_result.json"
  local stdout_path="${case_dir}/stdout.log"
  local stderr_path="${case_dir}/stderr.log"
  local start end duration rc

  mkdir -p "${case_dir}"
  start="$(now_ms)"
  if python "${CLI_SCRIPT}" "$@" --output-dir "${case_dir}" --artifact-path "${artifact_path}" >"${stdout_path}" 2>"${stderr_path}"; then
    rc=0
  else
    rc=$?
  fi
  end="$(now_ms)"
  duration=$((end - start))

  printf '%s|%s|%s|%s|%s\n' "${rc}" "${artifact_path}" "${stdout_path}" "${stderr_path}" "${duration}"
}

validate_artifact() {
  local artifact_path="$1"
  python "${VALIDATE_JSON}" \
    --schema "${SCHEMA_PATH}" \
    --input "${artifact_path}"
}

assert_four_stems() {
  local case_dir="$1"
  python - <<'PY' "${case_dir}"
from pathlib import Path
import sys

case_dir = Path(sys.argv[1])
stems = sorted(path.name for path in case_dir.glob("*.wav"))
if stems != ["bass.wav", "drums.wav", "other.wav", "vocals.wav"]:
    raise SystemExit(f"unexpected stem outputs for {case_dir.name}: {stems}")
for stem in stems:
    if (case_dir / stem).stat().st_size <= 0:
        raise SystemExit(f"empty stem output for {case_dir.name}: {stem}")
print(f"{case_dir.name}: four stems present")
PY
}

assert_supported_demucs_case() {
  local artifact_path="$1"
  local case_dir="$2"
  python - <<'PY' "${artifact_path}" "${case_dir}" "${DEMUCS_MODEL_PATH}"
import json
from pathlib import Path
import sys

artifact_path = Path(sys.argv[1])
case_dir = Path(sys.argv[2])
expected_model_path = sys.argv[3]
payload = json.loads(artifact_path.read_text(encoding="utf-8"))
if payload["status"] != "ok":
    raise SystemExit(f"unexpected status: {payload['status']}")
if payload["error_stage"] is not None:
    raise SystemExit(f"unexpected error stage: {payload['error_stage']}")
if payload["error_message"] is not None:
    raise SystemExit(f"unexpected error message: {payload['error_message']}")
if payload["health_state"] != "healthy":
    raise SystemExit(f"unexpected health state: {payload['health_state']}")
if payload["health_reason"] != "runtime operating normally":
    raise SystemExit(f"unexpected health reason: {payload['health_reason']}")
if payload["requested_model_path"] != expected_model_path:
    raise SystemExit(f"unexpected requested_model_path: {payload['requested_model_path']}")
if payload["model_path"] != expected_model_path:
    raise SystemExit(f"unexpected model_path: {payload['model_path']}")
if payload["fallback_applied"] is not False:
    raise SystemExit(f"unexpected fallback_applied: {payload['fallback_applied']}")
stem_paths = payload.get("stem_paths", {})
if sorted(stem_paths.keys()) != ["bass", "drums", "other", "vocals"]:
    raise SystemExit(f"unexpected stem keys for {case_dir.name}: {sorted(stem_paths.keys())}")
for stem_name in ["vocals", "drums", "bass", "other"]:
    expected_path = str(case_dir / f"{stem_name}.wav")
    if stem_paths.get(stem_name) != expected_path:
        raise SystemExit(f"unexpected {stem_name} path: {stem_paths.get(stem_name)}")
print(f"{case_dir.name}: supported Demucs four-stem artifact ok")
PY
}

assert_unsupported_fallback_case() {
  local artifact_path="$1"
  local case_dir="$2"
  local requested_model_path="$3"
  python - <<'PY' "${artifact_path}" "${case_dir}" "${requested_model_path}" "${DEFAULT_MODEL_PATH}"
import json
from pathlib import Path
import sys

artifact_path = Path(sys.argv[1])
case_dir = Path(sys.argv[2])
requested_model_path = sys.argv[3]
expected_model_path = sys.argv[4]
payload = json.loads(artifact_path.read_text(encoding="utf-8"))
if payload["status"] != "ok":
    raise SystemExit(f"unexpected status: {payload['status']}")
if payload["error_stage"] is not None:
    raise SystemExit(f"unexpected error stage: {payload['error_stage']}")
if payload["error_message"] is not None:
    raise SystemExit(f"unexpected error message: {payload['error_message']}")
if payload["health_state"] != "fallback":
    raise SystemExit(f"unexpected health state: {payload['health_state']}")
reason = str(payload["health_reason"])
if requested_model_path not in reason:
    raise SystemExit(f"missing requested model path in health_reason: {reason}")
if expected_model_path not in reason:
    raise SystemExit(f"missing fallback model path in health_reason: {reason}")
if payload["requested_model_path"] != requested_model_path:
    raise SystemExit(f"unexpected requested_model_path: {payload['requested_model_path']}")
if payload["model_path"] != expected_model_path:
    raise SystemExit(f"unexpected model_path: {payload['model_path']}")
if payload["fallback_applied"] is not True:
    raise SystemExit(f"unexpected fallback_applied: {payload['fallback_applied']}")
stem_paths = payload.get("stem_paths", {})
if sorted(stem_paths.keys()) != ["bass", "drums", "other", "vocals"]:
    raise SystemExit(f"unexpected stem keys for {case_dir.name}: {sorted(stem_paths.keys())}")
for stem_name in ["vocals", "drums", "bass", "other"]:
    expected_path = str(case_dir / f"{stem_name}.wav")
    if stem_paths.get(stem_name) != expected_path:
        raise SystemExit(f"unexpected {stem_name} path: {stem_paths.get(stem_name)}")
print(f"{case_dir.name}: unsupported fallback four-stem artifact ok")
PY
}

run_supported_case() {
  local label="$1"
  shift
  local run_result artifact_path stdout_path stderr_path duration rc case_dir
  run_result="$(run_cli_case "${label}" "$@")"
  IFS='|' read -r rc artifact_path stdout_path stderr_path duration <<<"${run_result}"
  case_dir="$(dirname "${artifact_path}")"

  if [[ "${rc}" -ne 0 ]]; then
    fail_case "${label}" "expected success but CLI exited ${rc}; artifact=${artifact_path}; stdout=${stdout_path}; stderr=${stderr_path}"
  fi
  [[ -f "${artifact_path}" ]] || fail_case "${label}" "missing runtime artifact at ${artifact_path}"
  validate_artifact "${artifact_path}" || fail_case "${label}" "schema validation failed for ${artifact_path}"
  assert_four_stems "${case_dir}"
  assert_supported_demucs_case "${artifact_path}" "${case_dir}"

  LAST_SUCCESSFUL_CASE="${label}"
  record_result "✅" "${label}" "${rc}" "${duration}"
}

run_fallback_case() {
  local label="$1"
  local requested_model_path="$2"
  shift 2
  local run_result artifact_path stdout_path stderr_path duration rc case_dir
  run_result="$(run_cli_case "${label}" "$@")"
  IFS='|' read -r rc artifact_path stdout_path stderr_path duration <<<"${run_result}"
  case_dir="$(dirname "${artifact_path}")"

  if [[ "${rc}" -ne 0 ]]; then
    fail_case "${label}" "expected success with fallback health but CLI exited ${rc}; artifact=${artifact_path}; stdout=${stdout_path}; stderr=${stderr_path}"
  fi
  [[ -f "${artifact_path}" ]] || fail_case "${label}" "missing runtime artifact at ${artifact_path}"
  validate_artifact "${artifact_path}" || fail_case "${label}" "schema validation failed for ${artifact_path}"
  assert_four_stems "${case_dir}"
  assert_unsupported_fallback_case "${artifact_path}" "${case_dir}" "${requested_model_path}"

  LAST_SUCCESSFUL_CASE="${label}"
  record_result "✅" "${label}" "${rc}" "${duration}"
}

run_supported_case \
  "supported-demucs-model-path" \
  --input "${MP3_FIXTURE}" \
  --model-path "${DEMUCS_MODEL_PATH}" \
  --chunk-duration-s 0.5 \
  --sample-rate-hz 22050

run_fallback_case \
  "unsupported-demucs-fallback-path" \
  "${UNSUPPORTED_MODEL_PATH}" \
  --input "${MP3_FIXTURE}" \
  --model-path "${UNSUPPORTED_MODEL_PATH}" \
  --chunk-duration-s 0.5 \
  --sample-rate-hz 22050

echo
echo "Verification evidence:"
printf "%-3s | %-28s | %-8s | %-10s\n" "" "check" "exit" "duration"
printf "%s\n" "----+------------------------------+----------+-----------"
for row in "${RESULTS[@]}"; do
  IFS='|' read -r verdict label rc duration <<<"${row}"
  printf "%-3s | %-28s | %-8s | %-10s\n" "${verdict}" "${label}" "${rc}" "${duration}"
done

echo
echo "Verifier artifacts: ${VERIFY_ROOT}"
echo "Last successful case: ${LAST_SUCCESSFUL_CASE}"
echo "m002_s01_check: PASS (${PASS_COUNT} checks)"
