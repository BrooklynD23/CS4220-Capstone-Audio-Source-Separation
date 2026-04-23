#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="."
CLI_SCRIPT="${PROJECT_ROOT}/scripts/live/run_live_separation.py"
SCHEMA_PATH="${PROJECT_ROOT}/artifacts/schema/live_runtime_result.schema.json"
MP3_FIXTURE="fixtures/audio/demo_mix.mp3"
VIDEO_FIXTURE="fixtures/video/demo_mix.mp4"
MISSING_VIDEO="fixtures/video/missing.mp4"
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/live"

mkdir -p "${ARTIFACT_ROOT}"
VERIFY_ROOT="$(mktemp -d "${ARTIFACT_ROOT}/s03-verify-XXXXXX")"

PASS_COUNT=0
FAIL_COUNT=0
RESULTS=()
LAST_SUCCESSFUL_MODE="none"

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

  echo "${rc}|${artifact_path}|${stdout_path}|${stderr_path}|${duration}"
}

assert_success_case() {
  local label="$1"
  local expected_kind="$2"
  local expected_reference="$3"
  local expected_metadata_json="$4"
  local run_result artifact_path stdout_path stderr_path duration rc case_dir
  run_result="$(run_cli_case "${label}" "${@:5}")"
  IFS='|' read -r rc artifact_path stdout_path stderr_path duration <<<"${run_result}"
  case_dir="$(dirname "${artifact_path}")"

  if [[ "${rc}" -ne 0 ]]; then
    echo "s03_check[${label}]: CLI failed with exit ${rc}" >&2
    echo "  artifact: ${artifact_path}" >&2
    echo "  stdout: ${stdout_path}" >&2
    echo "  stderr: ${stderr_path}" >&2
    record_result "❌" "${label}" "${rc}" "${duration}"
    return 1
  fi

  if [[ ! -f "${artifact_path}" ]]; then
    echo "s03_check[${label}]: missing runtime artifact" >&2
    record_result "❌" "${label}" "${rc}" "${duration}"
    return 1
  fi

  python "${PROJECT_ROOT}/scripts/verify/validate_json.py" \
    --schema "${SCHEMA_PATH}" \
    --input "${artifact_path}"

  python - <<'PY' "${artifact_path}" "${case_dir}" "${expected_kind}" "${expected_reference}" "${expected_metadata_json}"
import json
from pathlib import Path
import sys

artifact_path = Path(sys.argv[1])
case_dir = Path(sys.argv[2])
expected_kind = sys.argv[3]
expected_reference = sys.argv[4]
expected_metadata_json = sys.argv[5]
expected_metadata = json.loads(expected_metadata_json)
payload = json.loads(artifact_path.read_text(encoding="utf-8"))
stems = sorted(path.name for path in case_dir.glob("*.wav"))
if stems != ["bass.wav", "drums.wav", "other.wav", "vocals.wav"]:
    raise SystemExit(f"unexpected stem outputs for {case_dir.name}: {stems}")
stem_paths = payload.get("stem_paths", {})
if sorted(stem_paths.keys()) != ["bass", "drums", "other", "vocals"]:
    raise SystemExit(f"unexpected stem keys for {case_dir.name}: {sorted(stem_paths.keys())}")
for stem_name in ["vocals", "drums", "bass", "other"]:
    expected_path = str(case_dir / f"{stem_name}.wav")
    if stem_paths.get(stem_name) != expected_path:
        raise SystemExit(f"unexpected stem path for {stem_name}: {stem_paths.get(stem_name)}")
if payload["status"] != "ok":
    raise SystemExit(f"unexpected status for {case_dir.name}: {payload['status']}")
if payload["error_stage"] is not None:
    raise SystemExit(f"unexpected error stage for {case_dir.name}: {payload['error_stage']}")
if payload["health_state"] != "healthy":
    raise SystemExit(f"unexpected health state for {case_dir.name}: {payload['health_state']}")
if payload["health_reason"] != "runtime operating normally":
    raise SystemExit(f"unexpected health reason for {case_dir.name}: {payload['health_reason']}")
if payload["requested_model_path"] != payload["model_path"]:
    raise SystemExit(f"requested/model path mismatch for {case_dir.name}: {payload['requested_model_path']} != {payload['model_path']}")
if payload["fallback_applied"] is not False:
    raise SystemExit(f"unexpected fallback_applied for {case_dir.name}: {payload['fallback_applied']}")
if payload["source"]["kind"] != expected_kind:
    raise SystemExit(f"unexpected source kind for {case_dir.name}: {payload['source']['kind']}")
if payload["source"]["reference"] != expected_reference:
    raise SystemExit(f"unexpected source reference for {case_dir.name}: {payload['source']['reference']}")
actual_metadata = payload["source"].get("metadata", {})
if actual_metadata != expected_metadata:
    raise SystemExit(f"unexpected source metadata for {case_dir.name}: {actual_metadata}")
print(f"{case_dir.name}: schema-valid artifact with four stems")
PY

  LAST_SUCCESSFUL_MODE="${label}"
  record_result "✅" "${label}" "${rc}" "${duration}"
}

assert_failure_case() {
  local label="$1"
  local expected_stage="$2"
  local expected_kind="$3"
  local expected_reference="$4"
  local run_result artifact_path stdout_path stderr_path duration rc case_dir
  run_result="$(run_cli_case "${label}" "${@:5}")"
  IFS='|' read -r rc artifact_path stdout_path stderr_path duration <<<"${run_result}"
  case_dir="$(dirname "${artifact_path}")"

  if [[ "${rc}" -eq 0 ]]; then
    echo "s03_check[${label}]: expected failure but CLI exited 0" >&2
    record_result "❌" "${label}" "${rc}" "${duration}"
    return 1
  fi

  if [[ ! -f "${artifact_path}" ]]; then
    echo "s03_check[${label}]: missing failure artifact" >&2
    echo "  stderr: ${stderr_path}" >&2
    record_result "❌" "${label}" "${rc}" "${duration}"
    return 1
  fi

  python "${PROJECT_ROOT}/scripts/verify/validate_json.py" \
    --schema "${SCHEMA_PATH}" \
    --input "${artifact_path}"

  python - <<'PY' "${artifact_path}" "${expected_stage}" "${expected_kind}" "${expected_reference}"
import json
from pathlib import Path
import sys

artifact_path = Path(sys.argv[1])
expected_stage = sys.argv[2]
expected_kind = sys.argv[3]
expected_reference = sys.argv[4]
payload = json.loads(artifact_path.read_text(encoding="utf-8"))
if payload["status"] != "error":
    raise SystemExit(f"unexpected failure status: {payload['status']}")
if payload["error_stage"] != expected_stage:
    raise SystemExit(f"unexpected failure stage: {payload['error_stage']}")
stems = sorted(path.name for path in artifact_path.parent.glob("*.wav"))
if stems:
    raise SystemExit(f"unexpected stem outputs for failure artifact: {stems}")
stem_paths = payload.get("stem_paths", {})
if sorted(stem_paths.keys()) != ["bass", "drums", "other", "vocals"]:
    raise SystemExit(f"unexpected stem keys for failure artifact: {sorted(stem_paths.keys())}")
for stem_name in ["vocals", "drums", "bass", "other"]:
    expected_path = str(artifact_path.parent / f"{stem_name}.wav")
    if stem_paths.get(stem_name) != expected_path:
        raise SystemExit(f"unexpected stem path for failure artifact {stem_name}: {stem_paths.get(stem_name)}")
if payload["health_state"] != "degraded":
    raise SystemExit(f"unexpected failure health state: {payload['health_state']}")
if payload["requested_model_path"] != payload["model_path"]:
    raise SystemExit(f"requested/model path mismatch on failure: {payload['requested_model_path']} != {payload['model_path']}")
if payload["fallback_applied"] is not False:
    raise SystemExit(f"unexpected fallback_applied on failure: {payload['fallback_applied']}")
if payload["source"]["kind"] != expected_kind:
    raise SystemExit(f"unexpected failure source kind: {payload['source']['kind']}")
if payload["source"]["reference"] != expected_reference:
    raise SystemExit(f"unexpected failure source reference: {payload['source']['reference']}")
if not payload["error_message"]:
    raise SystemExit("missing failure message")
print(f"{artifact_path.parent.name}: failure artifact exposes {expected_stage}")
PY

  record_result "✅" "${label}" "${rc}" "${duration}"
}

assert_success_case \
  "mp3-source-mode" \
  "mp3" \
  "${MP3_FIXTURE}" \
  '{}' \
  --input "${MP3_FIXTURE}" \
  --chunk-duration-s 0.5 \
  --sample-rate-hz 22050 \
  --max-queue-depth 64

assert_success_case \
  "video-audio-source-mode" \
  "video_audio" \
  "${VIDEO_FIXTURE}" \
  '{"container": "mp4"}' \
  --source-mode video-audio \
  --input "${VIDEO_FIXTURE}" \
  --chunk-duration-s 0.5 \
  --sample-rate-hz 22050 \
  --max-queue-depth 64

assert_success_case \
  "mic-source-mode" \
  "mic" \
  "fixture:mic-demo" \
  '{"backend": "fake", "device": "fixture:mic-demo", "capture_duration_s": 1.0, "sample_rate_hz": 22050}' \
  --source-mode mic \
  --mic-backend fake \
  --mic-device fixture:mic-demo \
  --chunk-duration-s 0.5 \
  --sample-rate-hz 22050 \
  --capture-duration-s 1.0 \
  --max-queue-depth 64

assert_failure_case \
  "video-audio-missing-input" \
  "decode_failed" \
  "video_audio" \
  "${MISSING_VIDEO}" \
  --source-mode video-audio \
  --input "${MISSING_VIDEO}" \
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
echo "Last successful mode: ${LAST_SUCCESSFUL_MODE}"

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
  echo "s03_check: FAIL (${FAIL_COUNT} failed, ${PASS_COUNT} passed)" >&2
  exit 1
fi

echo "s03_check: PASS (${PASS_COUNT} checks)"
