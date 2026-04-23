#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="."
LAUNCHER="${PROJECT_ROOT}/scripts/ui/serve_compare_demo.py"
TEST_FILE="${PROJECT_ROOT}/tests/ui/test_compare_ui.py"
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/live"
SERVER_LOG_DIR=""
PYTEST_LOG_DIR=""
SERVER_LOG=""
PYTEST_LOG=""
SERVER_PID=""
BASE_URL=""
PASS_COUNT=0
FAIL_COUNT=0
RESULTS=()

mkdir -p "${ARTIFACT_ROOT}"
SERVER_LOG_DIR="$(mktemp -d "${ARTIFACT_ROOT}/s05-verify-server-XXXXXX")"
PYTEST_LOG_DIR="$(mktemp -d "${ARTIFACT_ROOT}/s05-verify-pytest-XXXXXX")"
SERVER_LOG="${SERVER_LOG_DIR}/server.log"
PYTEST_LOG="${PYTEST_LOG_DIR}/pytest.log"

cleanup() {
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

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

fail() {
  local label="$1"
  local message="$2"
  local rc="${3:-1}"
  echo "s05_check[${label}]: ${message}" >&2
  echo "Server log: ${SERVER_LOG}" >&2
  echo "Pytest log: ${PYTEST_LOG}" >&2
  if [[ -f "${SERVER_LOG}" ]]; then
    echo "--- server log ---" >&2
    tail -n 80 "${SERVER_LOG}" >&2 || true
  fi
  if [[ -f "${PYTEST_LOG}" ]]; then
    echo "--- pytest log ---" >&2
    tail -n 120 "${PYTEST_LOG}" >&2 || true
  fi
  exit "${rc}"
}

find_free_port() {
  python - <<'PY'
import socket
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
}

wait_for_server() {
  local url="$1"
  local timeout_s="${2:-20}"
  local start now
  start="$(date +%s)"
  while true; do
    if python - "$url" <<'PY' >/dev/null 2>&1; then
import sys
from urllib.request import urlopen
try:
    with urlopen(sys.argv[1], timeout=1) as response:
        if response.status != 200:
            raise SystemExit(1)
except Exception:
    raise SystemExit(1)
PY
      return 0
    fi

    if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
      return 1
    fi

    now="$(date +%s)"
    if (( now - start >= timeout_s )); then
      return 1
    fi
    sleep 0.25
  done
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
  if [[ "${rc}" -eq 0 ]]; then
    record_result "✅" "${label}" "${rc}" "${duration}"
  else
    record_result "❌" "${label}" "${rc}" "${duration}"
  fi
  return "${rc}"
}

run_server_smoke() {
  local url="$1"
  python - "$url" <<'PY'
import sys
from urllib.request import urlopen
url = sys.argv[1]
with urlopen(url, timeout=2) as response:
    body = response.read().decode("utf-8", errors="replace")
if response.status != 200:
    raise SystemExit(f"unexpected status: {response.status}")
if "Persisted artifact compare" not in body:
    raise SystemExit("compare UI shell did not load")
print("launcher smoke: compare UI shell reachable")
PY
}

run_pytest_suite() {
  COMPARE_DEMO_BASE_URL="${BASE_URL}" \
  BASE_URL="${BASE_URL}" \
  pytest "${TEST_FILE}" -q >"${PYTEST_LOG}" 2>&1
}

PORT="$(find_free_port)"
BASE_URL="http://127.0.0.1:${PORT}"

python "${LAUNCHER}" --bind 127.0.0.1 --port "${PORT}" --directory "${PROJECT_ROOT}" >"${SERVER_LOG}" 2>&1 &
SERVER_PID=$!

if ! wait_for_server "${BASE_URL}/ui/compare/" 30; then
  fail "launcher-start" "server did not become ready at ${BASE_URL}/ui/compare/"
fi

run_check "launcher-smoke" run_server_smoke "${BASE_URL}/ui/compare/" || fail "launcher-smoke" "launcher smoke check failed"
run_check "pytest-suite" run_pytest_suite || fail "pytest-suite" "compare UI pytest suite failed"

echo
echo "Verification evidence:"
printf "%-3s | %-28s | %-8s | %-10s\n" "" "check" "exit" "duration"
printf "%s\n" "----+------------------------------+----------+-----------"
for row in "${RESULTS[@]}"; do
  IFS='|' read -r verdict label rc duration <<<"${row}"
  printf "%-3s | %-28s | %-8s | %-10s\n" "${verdict}" "${label}" "${rc}" "${duration}"
done

echo
echo "Server log: ${SERVER_LOG}"
echo "Pytest log: ${PYTEST_LOG}"
echo "Base URL: ${BASE_URL}"

echo "s05_check: PASS (${PASS_COUNT} checks)"
