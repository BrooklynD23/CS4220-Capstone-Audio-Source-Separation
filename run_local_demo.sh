#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_VENV_DIR="${PROJECT_ROOT}/.venv"
DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/artifacts/live/one-click"
DEFAULT_ARTIFACT_PATH="${DEFAULT_OUTPUT_DIR}/live_runtime_result.json"
DEFAULT_UI_BIND="127.0.0.1"
DEFAULT_UI_PORT="8000"
DEFAULT_SOURCE_MODE="mp3"
DEFAULT_RUNTIME_MODE="smoke"
DEFAULT_MIC_BACKEND="fake"
DEFAULT_DEVICE="cpu"

VENV_DIR="${VENV_DIR:-${DEFAULT_VENV_DIR}}"
OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
ARTIFACT_PATH="${DEFAULT_ARTIFACT_PATH}"
UI_BIND="${DEFAULT_UI_BIND}"
UI_PORT="${DEFAULT_UI_PORT}"
SOURCE_MODE="${DEFAULT_SOURCE_MODE}"
RUNTIME_MODE="${DEFAULT_RUNTIME_MODE}"
MIC_BACKEND="${DEFAULT_MIC_BACKEND}"
MIC_DEVICE="default"
DEVICE="${DEFAULT_DEVICE}"
INPUT_PATH=""
SKIP_INSTALL="false"
WITH_GPU="false"
WITH_MIC="false"

usage() {
  cat <<'EOF'
Usage: bash run_local_demo.sh [options]

Creates or reuses .venv, installs project dependencies, runs the live separation CLI
to generate a fresh artifact, then starts the compare UI with that artifact preloaded.

Options:
  --source-mode <mp3|video-audio|mic>  Source used for the backend run. Default: mp3
  --input <path>                       Optional input file for mp3 or video-audio mode
  --output-dir <path>                  Output directory for generated stems and JSON
  --ui-bind <host>                     UI bind address. Default: 127.0.0.1
  --ui-port <port>                     UI port. Default: 8000
  --mode <smoke|full>                  Backend runtime mode. Default: smoke
  --device <cpu|gpu>                   Device metadata forwarded to the backend. Default: cpu
  --mic-backend <fake|sounddevice>     Mic backend when --source-mode mic is used. Default: fake
  --mic-device <name>                  Mic device identifier. Default: default
  --with-gpu                           Install the optional gpu extra
  --with-mic                           Install the optional mic extra
  --skip-install                       Reuse the current environment without pip install
  --help                               Show this help text

Examples:
  bash run_local_demo.sh
  bash run_local_demo.sh --source-mode video-audio --mode smoke
  bash run_local_demo.sh --source-mode mic --mic-backend sounddevice --with-mic
  bash run_local_demo.sh --mode full --device gpu --with-gpu
EOF
}

fail() {
  echo "run_local_demo: $*" >&2
  exit 1
}

python_supports_project() {
  local python_cmd="$1"
  "${python_cmd}" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if (3, 10) <= sys.version_info < (3, 13) else 1)
PY
}

find_python() {
  local -a candidates=()
  local candidate
  local -a found_versions=()

  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
      fail "PYTHON_BIN is set to '${PYTHON_BIN}', but that executable was not found."
    fi
    if python_supports_project "${PYTHON_BIN}"; then
      printf '%s\n' "${PYTHON_BIN}"
      return 0
    fi
    fail "PYTHON_BIN points to an unsupported interpreter. Use Python >=3.10,<3.13."
  fi

  candidates=(python3.12 python3.11 python3.10 python3 python)

  for candidate in "${candidates[@]}"; do
    if command -v "${candidate}" >/dev/null 2>&1 && python_supports_project "${candidate}"; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  for candidate in "${candidates[@]}"; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      found_versions+=("${candidate}=$("${candidate}" -c 'import sys; print(sys.version.split()[0])')") || true
    fi
  done

  if [[ ${#found_versions[@]} -gt 0 ]]; then
    fail "No compatible Python interpreter found. Detected: ${found_versions[*]}. Use Python >=3.10,<3.13, set PYTHON_BIN, or on Windows run run_local_demo.bat."
  fi

  fail "Python >=3.10,<3.13 is required, but no Python interpreter was found in PATH. On Windows, run run_local_demo.bat."
}

ensure_python_version() {
  local python_cmd="$1"
  "${python_cmd}" - <<'PY'
import sys
if sys.version_info < (3, 10) or sys.version_info >= (3, 13):
    raise SystemExit(
        f"run_local_demo: Python {sys.version.split()[0]} is unsupported. "
        "Use Python >=3.10,<3.13."
    )
PY
}

join_by_comma() {
  local first="true"
  local joined=""
  local item
  for item in "$@"; do
    if [[ "${first}" == "true" ]]; then
      joined="${item}"
      first="false"
    else
      joined="${joined},${item}"
    fi
  done
  printf '%s\n' "${joined}"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --source-mode)
        [[ $# -ge 2 ]] || fail "Missing value for --source-mode"
        SOURCE_MODE="$2"
        shift 2
        ;;
      --input)
        [[ $# -ge 2 ]] || fail "Missing value for --input"
        INPUT_PATH="$2"
        shift 2
        ;;
      --output-dir)
        [[ $# -ge 2 ]] || fail "Missing value for --output-dir"
        OUTPUT_DIR="$2"
        ARTIFACT_PATH="${OUTPUT_DIR}/live_runtime_result.json"
        shift 2
        ;;
      --ui-bind)
        [[ $# -ge 2 ]] || fail "Missing value for --ui-bind"
        UI_BIND="$2"
        shift 2
        ;;
      --ui-port)
        [[ $# -ge 2 ]] || fail "Missing value for --ui-port"
        UI_PORT="$2"
        shift 2
        ;;
      --mode)
        [[ $# -ge 2 ]] || fail "Missing value for --mode"
        RUNTIME_MODE="$2"
        shift 2
        ;;
      --device)
        [[ $# -ge 2 ]] || fail "Missing value for --device"
        DEVICE="$2"
        shift 2
        ;;
      --mic-backend)
        [[ $# -ge 2 ]] || fail "Missing value for --mic-backend"
        MIC_BACKEND="$2"
        shift 2
        ;;
      --mic-device)
        [[ $# -ge 2 ]] || fail "Missing value for --mic-device"
        MIC_DEVICE="$2"
        shift 2
        ;;
      --with-gpu)
        WITH_GPU="true"
        shift
        ;;
      --with-mic)
        WITH_MIC="true"
        shift
        ;;
      --skip-install)
        SKIP_INSTALL="true"
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        fail "Unknown argument: $1"
        ;;
    esac
  done
}

validate_args() {
  case "${SOURCE_MODE}" in
    mp3|video-audio|mic) ;;
    *) fail "--source-mode must be one of: mp3, video-audio, mic" ;;
  esac

  case "${RUNTIME_MODE}" in
    smoke|full) ;;
    *) fail "--mode must be one of: smoke, full" ;;
  esac

  case "${DEVICE}" in
    cpu|gpu) ;;
    *) fail "--device must be one of: cpu, gpu" ;;
  esac

  case "${MIC_BACKEND}" in
    fake|sounddevice) ;;
    *) fail "--mic-backend must be one of: fake, sounddevice" ;;
  esac

  if [[ -n "${INPUT_PATH}" && "${SOURCE_MODE}" == "mic" ]]; then
    fail "--input cannot be used with --source-mode mic"
  fi

  if [[ "${SOURCE_MODE}" == "mic" && "${MIC_BACKEND}" == "sounddevice" ]]; then
    WITH_MIC="true"
  fi

  if [[ "${RUNTIME_MODE}" == "full" || "${DEVICE}" == "gpu" ]]; then
    WITH_GPU="true"
  fi
}

create_venv_if_needed() {
  local venv_python="${VENV_DIR}/bin/python"
  local python_cmd

  if [[ -x "${venv_python}" ]] && python_supports_project "${venv_python}"; then
    echo "run_local_demo: reusing virtual environment at ${VENV_DIR}"
    return 0
  fi

  python_cmd="$(find_python)"
  ensure_python_version "${python_cmd}"

  if [[ -x "${venv_python}" ]]; then
    echo "run_local_demo: rebuilding virtual environment at ${VENV_DIR} with ${python_cmd}"
    "${python_cmd}" -m venv --clear "${VENV_DIR}"
  else
    echo "run_local_demo: creating virtual environment at ${VENV_DIR} with ${python_cmd}"
    "${python_cmd}" -m venv "${VENV_DIR}"
  fi
}

install_dependencies() {
  local venv_python="$1"
  local extras=("dev")
  local joined_extras

  if [[ "${WITH_GPU}" == "true" ]]; then
    extras+=("gpu")
  fi
  if [[ "${WITH_MIC}" == "true" ]]; then
    extras+=("mic")
  fi

  joined_extras="$(join_by_comma "${extras[@]}")"
  echo "run_local_demo: installing project dependencies with extras [${joined_extras}]"
  (
    cd "${PROJECT_ROOT}"
    "${venv_python}" -m pip install -e ".[$(join_by_comma "${extras[@]}")]"
  )
}

build_backend_command() {
  local venv_python="$1"
  local -a command=(
    "${venv_python}"
    "${PROJECT_ROOT}/scripts/live/run_live_separation.py"
    --source-mode "${SOURCE_MODE}"
    --output-dir "${OUTPUT_DIR}"
    --artifact-path "${ARTIFACT_PATH}"
    --mode "${RUNTIME_MODE}"
    --device-requested "${DEVICE}"
    --device-used "${DEVICE}"
    --mic-backend "${MIC_BACKEND}"
    --mic-device "${MIC_DEVICE}"
  )

  if [[ -n "${INPUT_PATH}" ]]; then
    command+=(--input "${INPUT_PATH}")
  fi

  printf '%s\0' "${command[@]}"
}

main() {
  local venv_python
  local artifact_relative_path
  local encoded_artifact_path
  local ui_url
  local -a backend_command=()

  parse_args "$@"
  validate_args
  cd "${PROJECT_ROOT}"

  create_venv_if_needed
  venv_python="${VENV_DIR}/bin/python"
  [[ -x "${venv_python}" ]] || fail "Virtual environment python not found at ${venv_python}"
  ensure_python_version "${venv_python}"

  if [[ "${SKIP_INSTALL}" != "true" ]]; then
    install_dependencies "${venv_python}"
  else
    echo "run_local_demo: skipping dependency installation"
  fi

  mkdir -p "${OUTPUT_DIR}"

  while IFS= read -r -d '' token; do
    backend_command+=("${token}")
  done < <(build_backend_command "${venv_python}")

  echo "run_local_demo: running backend artifact generation"
  "${backend_command[@]}"

  artifact_relative_path="${ARTIFACT_PATH#${PROJECT_ROOT}/}"
  if [[ "${artifact_relative_path}" == "${ARTIFACT_PATH}" ]]; then
    fail "Artifact path must stay inside the repository so the UI can serve it."
  fi

  encoded_artifact_path="$("${venv_python}" - "${artifact_relative_path}" <<'PY'
from urllib.parse import quote
import sys

print("/" + quote(sys.argv[1], safe="/"))
PY
)"
  ui_url="http://${UI_BIND}:${UI_PORT}/ui/compare/?artifact=${encoded_artifact_path}"
  echo "run_local_demo: artifact ready at ${ARTIFACT_PATH}"
  echo "run_local_demo: starting compare UI at ${ui_url}"
  echo "run_local_demo: press Ctrl+C to stop the server"

  exec "${venv_python}" "${PROJECT_ROOT}/scripts/ui/serve_compare_demo.py" \
    --bind "${UI_BIND}" \
    --port "${UI_PORT}" \
    --directory "${PROJECT_ROOT}"
}

main "$@"
