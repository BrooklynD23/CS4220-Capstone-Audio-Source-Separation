#!/usr/bin/env bash
set -u

PROJECT_ROOT="."
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/bench"
BUNDLE_DIR="$(mktemp -d "${ARTIFACT_ROOT}/s06-capstone-XXXXXX")"
LIVE_DIR="${BUNDLE_DIR}/live"
THROUGHPUT_DIR="${BUNDLE_DIR}/throughput"
MIC_DIR="${BUNDLE_DIR}/mic-latency"
LIVE_ARTIFACT_PATH="${LIVE_DIR}/live_runtime_result.json"
THROUGHPUT_ARTIFACT_PATH="${THROUGHPUT_DIR}/live_throughput_result.json"
THROUGHPUT_LIVE_ARTIFACT_PATH="${THROUGHPUT_DIR}/live_runtime_result.json"
MIC_ARTIFACT_PATH="${MIC_DIR}/mic_latency_result.json"
MIC_LIVE_ARTIFACT_PATH="${MIC_DIR}/live_runtime_result.json"
MANIFEST_PATH="${ARTIFACT_ROOT}/capstone_evidence_manifest.json"
EVAL_SUMMARY_PATH="${PROJECT_ROOT}/artifacts/eval/summary-smoke.json"
THROUGHPUT_SCHEMA_PATH="${PROJECT_ROOT}/artifacts/schema/live_throughput_result.schema.json"
MIC_SCHEMA_PATH="${PROJECT_ROOT}/artifacts/schema/mic_latency_result.schema.json"
LIVE_SCHEMA_PATH="${PROJECT_ROOT}/artifacts/schema/live_runtime_result.schema.json"
PASS_COUNT=0
FAIL_COUNT=0
RESULTS=()

mkdir -p "${LIVE_DIR}" "${THROUGHPUT_DIR}" "${MIC_DIR}"

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
  if "$@"; then
    rc=0
  else
    rc=$?
  fi
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

latest_path() {
  python - "$@" <<'PY'
from pathlib import Path
import sys

patterns = sys.argv[1:]
candidates: list[Path] = []
for pattern in patterns:
    candidates.extend(sorted(Path('.').glob(pattern)))
existing = [path for path in candidates if path.exists()]
if not existing:
    raise SystemExit(1)
latest = max(existing, key=lambda path: (path.stat().st_mtime_ns, path.as_posix()))
print(latest)
PY
}

check_manifest() {
  python - "${MANIFEST_PATH}" <<'PY'
from pathlib import Path
import json
import sys

manifest_path = Path(sys.argv[1])
payload = json.loads(manifest_path.read_text(encoding='utf-8'))
expected_order = ["evaluation", "throughput", "mic_latency", "live_runtime", "compare_ui"]
if payload.get("status") != "ok":
    raise SystemExit(f"unexpected manifest status: {payload.get('status')}")
if payload.get("phase") != "complete":
    raise SystemExit(f"unexpected manifest phase: {payload.get('phase')}")
if payload.get("error_stage") is not None:
    raise SystemExit(f"unexpected manifest error_stage: {payload.get('error_stage')}")
if payload.get("phase_order") != expected_order:
    raise SystemExit(f"unexpected phase_order: {payload.get('phase_order')}")
phase_names = [phase.get("name") for phase in payload.get("phases", [])]
if phase_names != expected_order:
    raise SystemExit(f"unexpected phase sequence: {phase_names}")
if not payload.get("inputs"):
    raise SystemExit("missing manifest inputs")
print("manifest ordering and status: ok")
PY
}

run_check "s01 verifier" bash scripts/verify/s01_check.sh
run_check "s02 verifier" bash scripts/verify/s02_check.sh
run_check "s03 verifier" bash scripts/verify/s03_check.sh
run_check "s04 verifier" bash scripts/verify/s04_check.sh
run_check "s05 verifier" bash scripts/verify/s05_check.sh

run_check "live runtime smoke" \
  python scripts/live/run_live_separation.py \
    --input fixtures/audio/demo_mix.mp3 \
    --output-dir "${LIVE_DIR}" \
    --artifact-path "${LIVE_ARTIFACT_PATH}"

run_check "validate live runtime schema" \
  python scripts/verify/validate_json.py \
    --schema "${LIVE_SCHEMA_PATH}" \
    --input "${LIVE_ARTIFACT_PATH}"

run_check "validate live runtime stems" \
  python - <<'PY' "${LIVE_ARTIFACT_PATH}" "${LIVE_DIR}"
import json
from pathlib import Path
import sys

artifact_path = Path(sys.argv[1])
output_dir = Path(sys.argv[2])
payload = json.loads(artifact_path.read_text(encoding="utf-8"))
expected_stems = ["bass.wav", "drums.wav", "other.wav", "vocals.wav"]
actual_stems = sorted(path.name for path in output_dir.glob("*.wav"))
if actual_stems != expected_stems:
    raise SystemExit(f"unexpected stem outputs for {output_dir.name}: {actual_stems}")
stem_paths = payload.get("stem_paths", {})
if sorted(stem_paths.keys()) != ["bass", "drums", "other", "vocals"]:
    raise SystemExit(f"unexpected stem path keys: {sorted(stem_paths.keys())}")
if payload["status"] != "ok":
    raise SystemExit(f"unexpected status: {payload['status']}")
if payload["health_state"] != "healthy":
    raise SystemExit(f"unexpected health state: {payload['health_state']}")
if payload["health_reason"] != "runtime operating normally":
    raise SystemExit(f"unexpected health reason: {payload['health_reason']}")
if payload["fallback_applied"] is not False:
    raise SystemExit(f"unexpected fallback_applied: {payload['fallback_applied']}")
if payload["requested_model_path"] != payload["model_path"]:
    raise SystemExit(f"requested/model path mismatch: {payload['requested_model_path']} != {payload['model_path']}")
for stem_name in ["vocals", "drums", "bass", "other"]:
    expected_path = str(output_dir / f"{stem_name}.wav")
    if stem_paths.get(stem_name) != expected_path:
        raise SystemExit(f"unexpected stem path for {stem_name}: {stem_paths.get(stem_name)}")
print(f"{output_dir.name}: live runtime stem contract ok")
PY
run_check "live throughput benchmark" \
  python scripts/benchmark/run_live_throughput.py \
    --input fixtures/audio/demo_mix.mp3 \
    --output-dir "${THROUGHPUT_DIR}" \
    --artifact-path "${THROUGHPUT_ARTIFACT_PATH}" \
    --live-artifact-path "${THROUGHPUT_LIVE_ARTIFACT_PATH}"

run_check "validate throughput schema" \
  python scripts/verify/validate_json.py \
    --schema "${THROUGHPUT_SCHEMA_PATH}" \
    --input "${THROUGHPUT_ARTIFACT_PATH}"

run_check "mic latency benchmark" \
  python scripts/benchmark/run_mic_latency.py \
    --output-dir "${MIC_DIR}" \
    --artifact-path "${MIC_ARTIFACT_PATH}" \
    --live-artifact-path "${MIC_LIVE_ARTIFACT_PATH}" \
    --mic-backend fake \
    --mic-device fixture:mic-demo \
    --capture-duration-s 1.0

run_check "validate mic schema" \
  python scripts/verify/validate_json.py \
    --schema "${MIC_SCHEMA_PATH}" \
    --input "${MIC_ARTIFACT_PATH}"

COMPARE_SERVER_LOG="$(latest_path 'artifacts/live/s05-verify-server-*/server.log')"
COMPARE_PYTEST_LOG="$(latest_path 'artifacts/live/s05-verify-pytest-*/pytest.log')"

run_check "assemble capstone manifest" \
  python scripts/benchmark/assemble_capstone_evidence.py \
    --output "${MANIFEST_PATH}" \
    --evaluation-summary "${EVAL_SUMMARY_PATH}" \
    --throughput-artifact "${THROUGHPUT_ARTIFACT_PATH}" \
    --mic-latency-artifact "${MIC_ARTIFACT_PATH}" \
    --live-runtime-artifact "${LIVE_ARTIFACT_PATH}" \
    --compare-server-log "${COMPARE_SERVER_LOG}" \
    --compare-pytest-log "${COMPARE_PYTEST_LOG}"

run_check "inspect manifest" check_manifest

echo
printf "%-3s | %-36s | %-8s | %-10s\n" "" "check" "exit" "duration"
printf "%s\n" "----+--------------------------------------+----------+-----------"
for row in "${RESULTS[@]}"; do
  IFS='|' read -r verdict label rc duration <<<"$row"
  printf "%-3s | %-36s | %-8s | %-10s\n" "$verdict" "$label" "$rc" "$duration"
done

echo
echo "Evidence paths:"
echo "- ${LIVE_ARTIFACT_PATH}"
echo "- ${THROUGHPUT_ARTIFACT_PATH}"
echo "- ${MIC_ARTIFACT_PATH}"
echo "- ${MANIFEST_PATH}"
echo "- ${COMPARE_SERVER_LOG}"
echo "- ${COMPARE_PYTEST_LOG}"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo "s06_check: FAIL (${FAIL_COUNT} failed, ${PASS_COUNT} passed)" >&2
  exit 1
fi

echo "s06_check: PASS (${PASS_COUNT} checks)"
