#!/usr/bin/env bash
set -u

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/export/build_trt_engine.sh \
    --onnx <path.onnx> \
    --engine <path.engine> \
    --min-shape <BxCxS> \
    --opt-shape <BxCxS> \
    --max-shape <BxCxS> \
    [--timing-cache <path.cache>] \
    [--trtexec <path-or-name>] \
    [--timeout-s <seconds>] \
    [--fp16] [--dry-run] [--force]

Notes:
- Shapes must be three positive integers in BxCxS format (example: 1x2x44100)
- This wrapper prints the exact trtexec command before execution for reproducibility.
USAGE
}

fail() {
  echo "$1" >&2
  exit "$2"
}

now_iso() {
  python - <<'PY'
from datetime import datetime, UTC
print(datetime.now(UTC).isoformat())
PY
}

write_log() {
  local status="$1"
  local stage="$2"
  local message="$3"
  local ts
  ts="$(now_iso)"
  mkdir -p "$(dirname "$LOG_PATH")"
  cat >"$LOG_PATH" <<EOF
{
  "timestamp": "$ts",
  "status": "$status",
  "error_stage": ${stage:+"$stage"},
  "error_message": ${message:+"$message"},
  "onnx": "$ONNX_PATH",
  "engine": "$ENGINE_PATH",
  "timing_cache": "$TIMING_CACHE",
  "fp16": $([[ "$FP16" -eq 1 ]] && echo true || echo false),
  "dry_run": $([[ "$DRY_RUN" -eq 1 ]] && echo true || echo false)
}
EOF
}

validate_profile() {
  local label="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[0-9]+x[0-9]+x[0-9]+$ ]]; then
    fail "malformed profile ($label): '$value'. Expected BxCxS like 1x2x44100." 2
  fi
}

shape_to_dims() {
  local value="$1"
  IFS='x' read -r d0 d1 d2 <<<"$value"
  echo "$d0 $d1 $d2"
}

ONNX_PATH=""
ENGINE_PATH=""
MIN_SHAPE=""
OPT_SHAPE=""
MAX_SHAPE=""
TIMING_CACHE="artifacts/bench/trt/timing.cache"
TRTEXEC_BIN="trtexec"
TIMEOUT_S=600
FP16=0
DRY_RUN=0
FORCE=0
LOG_PATH="artifacts/bench/trt/build_log.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --onnx)
      ONNX_PATH="${2-}"; shift 2 ;;
    --engine)
      ENGINE_PATH="${2-}"; shift 2 ;;
    --min-shape)
      MIN_SHAPE="${2-}"; shift 2 ;;
    --opt-shape)
      OPT_SHAPE="${2-}"; shift 2 ;;
    --max-shape)
      MAX_SHAPE="${2-}"; shift 2 ;;
    --timing-cache)
      TIMING_CACHE="${2-}"; shift 2 ;;
    --trtexec)
      TRTEXEC_BIN="${2-}"; shift 2 ;;
    --timeout-s)
      TIMEOUT_S="${2-}"; shift 2 ;;
    --log-path)
      LOG_PATH="${2-}"; shift 2 ;;
    --fp16)
      FP16=1; shift ;;
    --dry-run)
      DRY_RUN=1; shift ;;
    --force)
      FORCE=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      usage
      fail "unknown argument: $1" 2 ;;
  esac
done

[[ -n "$ONNX_PATH" ]] || fail "missing required --onnx" 2
[[ -n "$ENGINE_PATH" ]] || fail "missing required --engine" 2
[[ -n "$MIN_SHAPE" ]] || fail "missing required --min-shape" 2
[[ -n "$OPT_SHAPE" ]] || fail "missing required --opt-shape" 2
[[ -n "$MAX_SHAPE" ]] || fail "missing required --max-shape" 2
[[ -n "$TIMING_CACHE" ]] || fail "timing-cache path must not be empty" 2

if [[ ! -f "$ONNX_PATH" ]]; then
  write_log "error" "build_failed" "ONNX file not found: $ONNX_PATH"
  fail "build_failed: ONNX file not found: $ONNX_PATH" 3
fi

validate_profile "min" "$MIN_SHAPE"
validate_profile "opt" "$OPT_SHAPE"
validate_profile "max" "$MAX_SHAPE"

read -r min_b min_c min_s <<<"$(shape_to_dims "$MIN_SHAPE")"
read -r opt_b opt_c opt_s <<<"$(shape_to_dims "$OPT_SHAPE")"
read -r max_b max_c max_s <<<"$(shape_to_dims "$MAX_SHAPE")"

if (( min_b > opt_b || opt_b > max_b || min_c > opt_c || opt_c > max_c || min_s > opt_s || opt_s > max_s )); then
  fail "malformed profile ordering: expected min<=opt<=max for all dims." 2
fi

if (( min_b != opt_b || opt_b != max_b || min_c != opt_c || opt_c != max_c )); then
  fail "malformed profile: only sample dimension may vary; batch/channels must stay fixed." 2
fi

mkdir -p "$(dirname "$ENGINE_PATH")"
mkdir -p "$(dirname "$TIMING_CACHE")"

CMD=(
  "$TRTEXEC_BIN"
  "--onnx=$ONNX_PATH"
  "--saveEngine=$ENGINE_PATH"
  "--minShapes=input:$MIN_SHAPE"
  "--optShapes=input:$OPT_SHAPE"
  "--maxShapes=input:$MAX_SHAPE"
  "--timingCacheFile=$TIMING_CACHE"
)
if [[ "$FP16" -eq 1 ]]; then
  CMD+=("--fp16")
fi

echo "trtexec command: ${CMD[*]}"

if [[ "$FORCE" -eq 0 && -f "$ENGINE_PATH" && "$DRY_RUN" -eq 0 ]]; then
  write_log "ok" "" "engine_exists_skip"
  echo "engine already exists; skipping rebuild (use --force to rebuild)"
  exit 0
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  : > "$ENGINE_PATH"
  : > "$TIMING_CACHE"
  write_log "ok" "" "dry_run"
  echo "dry_run: wrote placeholder engine + timing cache"
  exit 0
fi

if ! command -v "$TRTEXEC_BIN" >/dev/null 2>&1; then
  write_log "error" "build_failed" "trtexec not found: $TRTEXEC_BIN"
  fail "trtexec not found: $TRTEXEC_BIN. Install TensorRT tools or pass --trtexec <path>." 127
fi

set +e
if command -v timeout >/dev/null 2>&1; then
  timeout "${TIMEOUT_S}s" "${CMD[@]}"
  rc=$?
else
  "${CMD[@]}"
  rc=$?
fi
set -e

if [[ "$rc" -eq 0 ]]; then
  write_log "ok" "" "build_complete"
  echo "build_ok: $ENGINE_PATH"
  exit 0
fi

if [[ "$rc" -eq 124 ]]; then
  write_log "error" "build_timeout" "trtexec exceeded timeout_s=$TIMEOUT_S"
  fail "build_timeout: trtexec exceeded timeout (${TIMEOUT_S}s) for profile $MIN_SHAPE/$OPT_SHAPE/$MAX_SHAPE" 4
fi

write_log "error" "build_failed" "trtexec exited with status $rc"
fail "build_failed: trtexec exited with status $rc. Check CUDA/TensorRT compatibility and artifact permissions." "$rc"
