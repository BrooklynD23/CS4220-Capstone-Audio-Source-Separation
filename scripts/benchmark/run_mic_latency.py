from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from jsonschema import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from live_runtime.contracts import validate_live_runtime_result
from live_runtime.live_core import DEFAULT_MODEL_PATH
from live_runtime.mic_ingest import DEFAULT_MIC_BACKEND, DEFAULT_MIC_CAPTURE_DURATION_S

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIVE_CLI_SCRIPT = PROJECT_ROOT / "scripts/live/run_live_separation.py"
LIVE_RUNTIME_SCHEMA = PROJECT_ROOT / "artifacts/schema/live_runtime_result.schema.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts/bench/mic-latency"
DEFAULT_ARTIFACT_NAME = "mic_latency_result.json"
DEFAULT_LIVE_ARTIFACT_NAME = "live_runtime_result.json"
DEFAULT_CAPTURE_LATENCY_BUDGET_MS = None
DEFAULT_CHUNK_DURATION_S = 1.0
DEFAULT_SAMPLE_RATE_HZ = 22050
DEFAULT_MAX_QUEUE_DEPTH = 64
DEFAULT_DECODE_TIMEOUT_S = 30.0
DEFAULT_LIVE_TIMEOUT_S = 120.0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_child_path(output_dir: Path, artifact_path: Path, label: str) -> None:
    if artifact_path.parent != output_dir:
        raise ValueError(f"{label} must live inside output_dir: {artifact_path} (output_dir={output_dir})")


def _execution_kind(device_used: str, model_path: str) -> str:
    model_path_lower = model_path.lower()
    if "tensorrt" in model_path_lower or model_path_lower.endswith(".engine"):
        return "tensorrt"
    if device_used == "gpu":
        return "gpu_pytorch"
    return "cpu"


def _build_live_command(
    *,
    output_dir: Path,
    live_artifact_path: Path,
    device_requested: str,
    device_used: str,
    mode: str,
    chunk_duration_s: float,
    sample_rate_hz: int,
    max_queue_depth: int,
    decode_timeout_s: float,
    model_path: str,
    mic_backend: str,
    mic_device: str,
    capture_duration_s: float,
) -> list[str]:
    return [
        sys.executable,
        str(LIVE_CLI_SCRIPT),
        "--source-mode",
        "mic",
        "--output-dir",
        str(output_dir),
        "--artifact-path",
        str(live_artifact_path),
        "--chunk-duration-s",
        str(chunk_duration_s),
        "--sample-rate-hz",
        str(sample_rate_hz),
        "--max-queue-depth",
        str(max_queue_depth),
        "--decode-timeout-s",
        str(decode_timeout_s),
        "--device-requested",
        device_requested,
        "--device-used",
        device_used,
        "--mode",
        mode,
        "--model-path",
        model_path,
        "--mic-backend",
        mic_backend,
        "--mic-device",
        mic_device,
        "--capture-duration-s",
        str(capture_duration_s),
    ]


def _build_result_payload(
    *,
    input_path: str,
    output_dir: Path,
    live_artifact_path: Path,
    capture_backend_name: str,
    capture_duration_s: float,
    capture_latency_ms: float | None,
    end_to_end_latency_ms: float,
    device_requested: str,
    device_used: str,
    status: str,
    phase: str,
    error_stage: str | None,
    error_message: str | None,
    stderr: str,
    live_cli_exit_code: int | None,
    live_runtime_status: str | None,
    live_runtime_error_stage: str | None,
    live_runtime_error_message: str | None,
    clock_source: str,
    max_capture_latency_ms: float | None,
    live_timeout_s: float,
    live_command: list[str],
    execution_kind: str,
) -> dict[str, Any]:
    end_to_end_latency_ms = max(0.0, end_to_end_latency_ms)
    if capture_latency_ms is not None:
        capture_latency_ms = max(0.0, capture_latency_ms)
    return {
        "input": input_path,
        "output_dir": str(output_dir),
        "live_artifact_path": str(live_artifact_path),
        "capture_backend_name": capture_backend_name,
        "capture_duration_s": capture_duration_s,
        "capture_latency_ms": None if capture_latency_ms is None else round(capture_latency_ms, 6),
        "end_to_end_latency_ms": round(end_to_end_latency_ms, 6),
        "device_requested": device_requested,
        "device_used": device_used,
        "execution_kind": execution_kind,
        "status": status,
        "phase": phase,
        "error_stage": error_stage,
        "error_message": error_message,
        "stderr": stderr,
        "live_cli_exit_code": live_cli_exit_code,
        "live_runtime_status": live_runtime_status,
        "live_runtime_error_stage": live_runtime_error_stage,
        "live_runtime_error_message": live_runtime_error_message,
        "timestamp": _now_iso(),
        "metadata": {
            "clock_source": clock_source,
            "live_timeout_s": live_timeout_s,
            "max_capture_latency_ms": max_capture_latency_ms,
            "live_command": live_command,
            "device_requested": device_requested,
            "device_used": device_used,
            "capture_backend_name": capture_backend_name,
            "capture_duration_s": capture_duration_s,
            "source_mode": "mic",
            "model_path": DEFAULT_MODEL_PATH,
        },
    }


def _build_failure_payload(
    *,
    input_path: str,
    output_dir: Path,
    live_artifact_path: Path,
    capture_backend_name: str,
    capture_duration_s: float,
    capture_latency_ms: float | None,
    end_to_end_latency_ms: float,
    device_requested: str,
    device_used: str,
    phase: str,
    error_message: str,
    stderr: str,
    live_cli_exit_code: int | None,
    live_runtime_status: str | None,
    live_runtime_error_stage: str | None,
    live_runtime_error_message: str | None,
    clock_source: str,
    max_capture_latency_ms: float | None,
    live_timeout_s: float,
    live_command: list[str],
) -> dict[str, Any]:
    return _build_result_payload(
        input_path=input_path,
        output_dir=output_dir,
        live_artifact_path=live_artifact_path,
        capture_backend_name=capture_backend_name,
        capture_duration_s=capture_duration_s,
        capture_latency_ms=capture_latency_ms,
        end_to_end_latency_ms=end_to_end_latency_ms,
        device_requested=device_requested,
        device_used=device_used,
        status="error",
        phase=phase,
        error_stage=phase,
        error_message=error_message,
        stderr=stderr,
        live_cli_exit_code=live_cli_exit_code,
        live_runtime_status=live_runtime_status,
        live_runtime_error_stage=live_runtime_error_stage,
        live_runtime_error_message=live_runtime_error_message,
        clock_source=clock_source,
        max_capture_latency_ms=max_capture_latency_ms,
        live_timeout_s=live_timeout_s,
        live_command=live_command,
        execution_kind=_execution_kind(device_used, live_command[live_command.index("--model-path") + 1] if "--model-path" in live_command else DEFAULT_MODEL_PATH),
    )


def _load_and_validate_live_artifact(live_artifact_path: Path) -> dict[str, Any]:
    try:
        payload = _load_json(live_artifact_path)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"live runtime artifact not found: {live_artifact_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"live runtime artifact is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("live runtime artifact root must be a JSON object")

    validate_live_runtime_result(payload)
    return payload


def _run_live_cli(
    command: list[str],
    *,
    live_timeout_s: float,
    clock: Callable[[], float],
) -> tuple[subprocess.CompletedProcess[str] | None, float, str | None]:
    started_at = clock()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=live_timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        finished_at = clock()
        timeout_message = f"live CLI timed out after {live_timeout_s:.3f}s"
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        if stderr:
            timeout_message = f"{timeout_message}: {stderr.strip()}"
        return None, (finished_at - started_at) * 1000.0, timeout_message

    finished_at = clock()
    return completed, (finished_at - started_at) * 1000.0, None


def run_mic_latency_benchmark(
    *,
    output_dir: Path,
    artifact_path: Path | None = None,
    live_artifact_path: Path | None = None,
    capture_backend_name: str = DEFAULT_MIC_BACKEND,
    mic_device: str = "default",
    capture_duration_s: float = DEFAULT_MIC_CAPTURE_DURATION_S,
    device_requested: str = "cpu",
    device_used: str = "cpu",
    mode: str = "smoke",
    chunk_duration_s: float = DEFAULT_CHUNK_DURATION_S,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    max_queue_depth: int = DEFAULT_MAX_QUEUE_DEPTH,
    decode_timeout_s: float = DEFAULT_DECODE_TIMEOUT_S,
    model_path: str = DEFAULT_MODEL_PATH,
    max_capture_latency_ms: float | None = DEFAULT_CAPTURE_LATENCY_BUDGET_MS,
    live_timeout_s: float = DEFAULT_LIVE_TIMEOUT_S,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[dict[str, Any], int]:
    if chunk_duration_s <= 0:
        raise ValueError("chunk_duration_s must be positive")
    if capture_duration_s <= 0:
        raise ValueError("capture_duration_s must be positive")
    if not mic_device.strip():
        raise ValueError("mic_device must be non-empty")

    output_dir = Path(output_dir)
    artifact_path = Path(artifact_path) if artifact_path is not None else output_dir / DEFAULT_ARTIFACT_NAME
    live_artifact_path = (
        Path(live_artifact_path) if live_artifact_path is not None else output_dir / DEFAULT_LIVE_ARTIFACT_NAME
    )
    _ensure_child_path(output_dir, artifact_path, "artifact_path")
    _ensure_child_path(output_dir, live_artifact_path, "live_artifact_path")

    output_dir.mkdir(parents=True, exist_ok=True)

    live_command = _build_live_command(
        output_dir=output_dir,
        live_artifact_path=live_artifact_path,
        device_requested=device_requested,
        device_used=device_used,
        mode=mode,
        chunk_duration_s=chunk_duration_s,
        sample_rate_hz=sample_rate_hz,
        max_queue_depth=max_queue_depth,
        decode_timeout_s=decode_timeout_s,
        model_path=model_path,
        mic_backend=capture_backend_name,
        mic_device=mic_device,
        capture_duration_s=capture_duration_s,
    )

    completed, end_to_end_latency_ms, timeout_message = _run_live_cli(
        live_command,
        live_timeout_s=live_timeout_s,
        clock=clock,
    )

    live_payload: dict[str, Any] | None = None
    live_runtime_status: str | None = None
    live_runtime_error_stage: str | None = None
    live_runtime_error_message: str | None = None
    stderr = ""
    live_cli_exit_code: int | None = None
    capture_latency_ms: float | None = None

    if completed is not None:
        stderr = completed.stderr or ""
        live_cli_exit_code = completed.returncode

        if live_artifact_path.exists():
            try:
                live_payload = _load_and_validate_live_artifact(live_artifact_path)
            except FileNotFoundError as exc:
                failure_payload = _build_failure_payload(
                    input_path=mic_device,
                    output_dir=output_dir,
                    live_artifact_path=live_artifact_path,
                    capture_backend_name=capture_backend_name,
                    capture_duration_s=capture_duration_s,
                    capture_latency_ms=capture_latency_ms,
                    end_to_end_latency_ms=end_to_end_latency_ms,
                    device_requested=device_requested,
                    device_used=device_used,
                    phase="missing_runtime_artifact",
                    error_message=str(exc),
                    stderr=stderr,
                    live_cli_exit_code=live_cli_exit_code,
                    live_runtime_status=None,
                    live_runtime_error_stage=None,
                    live_runtime_error_message=None,
                    clock_source="perf_counter",
                    max_capture_latency_ms=max_capture_latency_ms,
                    live_timeout_s=live_timeout_s,
                    live_command=live_command,
                )
                _write_json(artifact_path, failure_payload)
                print(
                    f"mic_latency_benchmark_failed[missing_runtime_artifact]: {exc}",
                    file=sys.stderr,
                )
                return failure_payload, 1
            except ValueError as exc:
                failure_payload = _build_failure_payload(
                    input_path=mic_device,
                    output_dir=output_dir,
                    live_artifact_path=live_artifact_path,
                    capture_backend_name=capture_backend_name,
                    capture_duration_s=capture_duration_s,
                    capture_latency_ms=capture_latency_ms,
                    end_to_end_latency_ms=end_to_end_latency_ms,
                    device_requested=device_requested,
                    device_used=device_used,
                    phase="malformed_runtime_artifact",
                    error_message=str(exc),
                    stderr=stderr,
                    live_cli_exit_code=live_cli_exit_code,
                    live_runtime_status=None,
                    live_runtime_error_stage=None,
                    live_runtime_error_message=None,
                    clock_source="perf_counter",
                    max_capture_latency_ms=max_capture_latency_ms,
                    live_timeout_s=live_timeout_s,
                    live_command=live_command,
                )
                _write_json(artifact_path, failure_payload)
                print(
                    f"mic_latency_benchmark_failed[malformed_runtime_artifact]: {exc}",
                    file=sys.stderr,
                )
                return failure_payload, 1
            except ValidationError as exc:
                failure_payload = _build_failure_payload(
                    input_path=mic_device,
                    output_dir=output_dir,
                    live_artifact_path=live_artifact_path,
                    capture_backend_name=capture_backend_name,
                    capture_duration_s=capture_duration_s,
                    capture_latency_ms=capture_latency_ms,
                    end_to_end_latency_ms=end_to_end_latency_ms,
                    device_requested=device_requested,
                    device_used=device_used,
                    phase="invalid_runtime_payload",
                    error_message=str(exc),
                    stderr=stderr,
                    live_cli_exit_code=live_cli_exit_code,
                    live_runtime_status=None,
                    live_runtime_error_stage=None,
                    live_runtime_error_message=None,
                    clock_source="perf_counter",
                    max_capture_latency_ms=max_capture_latency_ms,
                    live_timeout_s=live_timeout_s,
                    live_command=live_command,
                )
                _write_json(artifact_path, failure_payload)
                print(
                    f"mic_latency_benchmark_failed[invalid_runtime_payload]: {exc}",
                    file=sys.stderr,
                )
                return failure_payload, 1
            else:
                live_runtime_status = (
                    str(live_payload.get("status")) if live_payload.get("status") is not None else None
                )
                live_runtime_error_stage = (
                    str(live_payload.get("error_stage")) if live_payload.get("error_stage") is not None else None
                )
                live_runtime_error_message = (
                    str(live_payload.get("error_message")) if live_payload.get("error_message") is not None else None
                )
                stft_ms = live_payload.get("stft_ms")
                capture_latency_ms = float(stft_ms) if stft_ms is not None else None
        elif completed.returncode == 0:
            failure_payload = _build_failure_payload(
                input_path=mic_device,
                output_dir=output_dir,
                live_artifact_path=live_artifact_path,
                capture_backend_name=capture_backend_name,
                capture_duration_s=capture_duration_s,
                capture_latency_ms=capture_latency_ms,
                end_to_end_latency_ms=end_to_end_latency_ms,
                device_requested=device_requested,
                device_used=device_used,
                phase="missing_runtime_artifact",
                error_message=f"expected live runtime artifact was not created: {live_artifact_path}",
                stderr=stderr,
                live_cli_exit_code=live_cli_exit_code,
                live_runtime_status=None,
                live_runtime_error_stage=None,
                live_runtime_error_message=None,
                clock_source="perf_counter",
                max_capture_latency_ms=max_capture_latency_ms,
                live_timeout_s=live_timeout_s,
                live_command=live_command,
            )
            _write_json(artifact_path, failure_payload)
            print(
                f"mic_latency_benchmark_failed[missing_runtime_artifact]: {live_artifact_path}",
                file=sys.stderr,
            )
            return failure_payload, 1

        if completed.returncode != 0:
            failure_stage = "live_cli_failed"
            failure_message = f"live CLI exited {completed.returncode}"
            if live_payload is not None and str(live_payload.get("status")) == "error":
                failure_stage = "live_runtime_failed"
                runtime_stage = live_payload.get("error_stage")
                runtime_message = live_payload.get("error_message")
                if runtime_stage:
                    failure_message = f"live runtime reported {runtime_stage}: {runtime_message or 'no error message'}"
            failure_payload = _build_failure_payload(
                input_path=mic_device,
                output_dir=output_dir,
                live_artifact_path=live_artifact_path,
                capture_backend_name=capture_backend_name,
                capture_duration_s=capture_duration_s,
                capture_latency_ms=capture_latency_ms,
                end_to_end_latency_ms=end_to_end_latency_ms,
                device_requested=device_requested,
                device_used=device_used,
                phase=failure_stage,
                error_message=failure_message,
                stderr=stderr,
                live_cli_exit_code=live_cli_exit_code,
                live_runtime_status=live_runtime_status,
                live_runtime_error_stage=live_runtime_error_stage,
                live_runtime_error_message=live_runtime_error_message,
                clock_source="perf_counter",
                max_capture_latency_ms=max_capture_latency_ms,
                live_timeout_s=live_timeout_s,
                live_command=live_command,
            )
            _write_json(artifact_path, failure_payload)
            print(
                f"mic_latency_benchmark_failed[{failure_stage}]: {failure_message}",
                file=sys.stderr,
            )
            return failure_payload, 1

    else:
        failure_payload = _build_failure_payload(
            input_path=mic_device,
            output_dir=output_dir,
            live_artifact_path=live_artifact_path,
            capture_backend_name=capture_backend_name,
            capture_duration_s=capture_duration_s,
            capture_latency_ms=capture_latency_ms,
            end_to_end_latency_ms=end_to_end_latency_ms,
            device_requested=device_requested,
            device_used=device_used,
            phase="live_cli_timeout",
            error_message=timeout_message or "live CLI timed out",
            stderr="",
            live_cli_exit_code=None,
            live_runtime_status=None,
            live_runtime_error_stage=None,
            live_runtime_error_message=None,
            clock_source="perf_counter",
            max_capture_latency_ms=max_capture_latency_ms,
            live_timeout_s=live_timeout_s,
            live_command=live_command,
        )
        _write_json(artifact_path, failure_payload)
        print(
            f"mic_latency_benchmark_failed[live_cli_timeout]: {timeout_message}",
            file=sys.stderr,
        )
        return failure_payload, 1

    if live_runtime_status != "ok":
        failure_stage = "live_runtime_failed"
        failure_message = f"live runtime reported status={live_runtime_status or 'unknown'}"
        if live_runtime_error_stage:
            failure_message = f"live runtime reported {live_runtime_error_stage}: {live_runtime_error_message or 'no error message'}"
        failure_payload = _build_failure_payload(
            input_path=mic_device,
            output_dir=output_dir,
            live_artifact_path=live_artifact_path,
            capture_backend_name=capture_backend_name,
            capture_duration_s=capture_duration_s,
            capture_latency_ms=capture_latency_ms,
            end_to_end_latency_ms=end_to_end_latency_ms,
            device_requested=device_requested,
            device_used=device_used,
            phase=failure_stage,
            error_message=failure_message,
            stderr=stderr,
            live_cli_exit_code=live_cli_exit_code,
            live_runtime_status=live_runtime_status,
            live_runtime_error_stage=live_runtime_error_stage,
            live_runtime_error_message=live_runtime_error_message,
            clock_source="perf_counter",
            max_capture_latency_ms=max_capture_latency_ms,
            live_timeout_s=live_timeout_s,
            live_command=live_command,
        )
        _write_json(artifact_path, failure_payload)
        print(
            f"mic_latency_benchmark_failed[{failure_stage}]: {failure_message}",
            file=sys.stderr,
        )
        return failure_payload, 1

    if capture_latency_ms is None and live_payload is not None:
        stft_ms = live_payload.get("stft_ms")
        capture_latency_ms = float(stft_ms) if stft_ms is not None else None

    budget_breached = max_capture_latency_ms is not None and capture_latency_ms is not None and capture_latency_ms > max_capture_latency_ms
    status = "error" if budget_breached else "ok"
    phase = "capture_latency_budget_exceeded" if budget_breached else "complete"
    error_stage = phase if budget_breached else None
    error_message = (
        f"mic capture latency exceeded: {capture_latency_ms:.3f}ms > {max_capture_latency_ms:.3f}ms"
        if budget_breached
        else None
    )
    result_payload = _build_result_payload(
        input_path=mic_device,
        output_dir=output_dir,
        live_artifact_path=live_artifact_path,
        capture_backend_name=capture_backend_name,
        capture_duration_s=capture_duration_s,
        capture_latency_ms=capture_latency_ms,
        end_to_end_latency_ms=end_to_end_latency_ms,
        device_requested=device_requested,
        device_used=device_used,
        status=status,
        phase=phase,
        error_stage=error_stage,
        error_message=error_message,
        stderr=stderr,
        live_cli_exit_code=live_cli_exit_code,
        live_runtime_status=live_runtime_status,
        live_runtime_error_stage=live_runtime_error_stage,
        live_runtime_error_message=live_runtime_error_message,
        clock_source="perf_counter",
        max_capture_latency_ms=max_capture_latency_ms,
        live_timeout_s=live_timeout_s,
        live_command=live_command,
        execution_kind=_execution_kind(device_used, model_path),
    )
    _write_json(artifact_path, result_payload)

    if budget_breached:
        print(
            f"mic_latency_benchmark_failed[capture_latency_budget_exceeded]: {error_message}",
            file=sys.stderr,
        )
        return result_payload, 1

    print(f"mic_latency_artifact: {artifact_path}")
    return result_payload, 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure mic capture latency through the live separation path.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory that will contain the mic latency and live runtime artifacts.",
    )
    parser.add_argument(
        "--artifact-path",
        type=Path,
        default=None,
        help="Path for the mic latency artifact. Defaults to <output-dir>/mic_latency_result.json.",
    )
    parser.add_argument(
        "--live-artifact-path",
        type=Path,
        default=None,
        help="Path for the live runtime artifact. Defaults to <output-dir>/live_runtime_result.json.",
    )
    parser.add_argument(
        "--mic-backend",
        choices=["fake", "sounddevice"],
        default=DEFAULT_MIC_BACKEND,
        help="Microphone backend forwarded to the live runtime CLI.",
    )
    parser.add_argument(
        "--mic-device",
        default="default",
        help="Microphone device identifier forwarded to the live runtime CLI.",
    )
    parser.add_argument(
        "--capture-duration-s",
        type=float,
        default=DEFAULT_MIC_CAPTURE_DURATION_S,
        help="Microphone capture duration forwarded to the live runtime CLI.",
    )
    parser.add_argument(
        "--device-requested",
        choices=["cpu", "gpu"],
        default="cpu",
        help="Requested runtime device recorded in the artifacts.",
    )
    parser.add_argument(
        "--device-used",
        choices=["cpu", "gpu"],
        default="cpu",
        help="Actual runtime device recorded in the artifacts.",
    )
    parser.add_argument(
        "--mode",
        choices=["smoke", "full"],
        default="smoke",
        help="Runtime mode forwarded to the live CLI.",
    )
    parser.add_argument(
        "--chunk-duration-s",
        type=float,
        default=DEFAULT_CHUNK_DURATION_S,
        help="Chunk duration forwarded to the live CLI.",
    )
    parser.add_argument(
        "--sample-rate-hz",
        type=int,
        default=DEFAULT_SAMPLE_RATE_HZ,
        help="Target sample rate forwarded to the live CLI.",
    )
    parser.add_argument(
        "--max-queue-depth",
        type=int,
        default=DEFAULT_MAX_QUEUE_DEPTH,
        help="Maximum queue depth forwarded to the live CLI.",
    )
    parser.add_argument(
        "--decode-timeout-s",
        type=float,
        default=DEFAULT_DECODE_TIMEOUT_S,
        help="Timeout forwarded to the live CLI for capture or decode.",
    )
    parser.add_argument(
        "--model-path",
        default=DEFAULT_MODEL_PATH,
        help="Model path forwarded to the live CLI.",
    )
    parser.add_argument(
        "--max-capture-latency-ms",
        type=float,
        default=DEFAULT_CAPTURE_LATENCY_BUDGET_MS,
        help="Optional latency budget for the mic capture latency measurement.",
    )
    parser.add_argument(
        "--live-timeout-s",
        type=float,
        default=DEFAULT_LIVE_TIMEOUT_S,
        help="Timeout for the live CLI subprocess.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        _, exit_code = run_mic_latency_benchmark(
            output_dir=args.output_dir,
            artifact_path=args.artifact_path,
            live_artifact_path=args.live_artifact_path,
            capture_backend_name=str(args.mic_backend),
            mic_device=str(args.mic_device),
            capture_duration_s=float(args.capture_duration_s),
            device_requested=str(args.device_requested),
            device_used=str(args.device_used),
            mode=str(args.mode),
            chunk_duration_s=float(args.chunk_duration_s),
            sample_rate_hz=int(args.sample_rate_hz),
            max_queue_depth=int(args.max_queue_depth),
            decode_timeout_s=float(args.decode_timeout_s),
            model_path=str(args.model_path),
            max_capture_latency_ms=args.max_capture_latency_ms,
            live_timeout_s=float(args.live_timeout_s),
        )
        return exit_code
    except (ValueError, FileNotFoundError) as exc:
        print(f"mic_latency_benchmark_config_error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover
        print(f"mic_latency_benchmark_failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
