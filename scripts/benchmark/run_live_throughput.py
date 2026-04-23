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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIVE_CLI_SCRIPT = PROJECT_ROOT / "scripts/live/run_live_separation.py"
LIVE_RUNTIME_SCHEMA = PROJECT_ROOT / "artifacts/schema/live_runtime_result.schema.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts/bench/live-throughput"
DEFAULT_ARTIFACT_NAME = "live_throughput_result.json"
DEFAULT_LIVE_ARTIFACT_NAME = "live_runtime_result.json"
DEFAULT_CHUNK_DURATION_S = 1.0
DEFAULT_SAMPLE_RATE_HZ = 22050
DEFAULT_MAX_QUEUE_DEPTH = 64
DEFAULT_DECODE_TIMEOUT_S = 30.0
DEFAULT_LIVE_TIMEOUT_S = 120.0
DEFAULT_MIC_CAPTURE_DURATION_S = 1.0


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


def _build_live_command(
    *,
    input_path: Path | None,
    output_dir: Path,
    live_artifact_path: Path,
    source_mode: str,
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
    command = [
        sys.executable,
        str(LIVE_CLI_SCRIPT),
        "--source-mode",
        source_mode,
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
    ]
    if input_path is not None:
        command.extend(["--input", str(input_path)])
    if source_mode == "mic":
        command.extend(
            [
                "--mic-backend",
                mic_backend,
                "--mic-device",
                mic_device,
                "--capture-duration-s",
                str(capture_duration_s),
            ]
        )
    return command


def _build_result_payload(
    *,
    input_path: str,
    output_dir: Path,
    live_artifact_path: Path,
    chunk_duration_s: float,
    wall_clock_ms: float,
    device_requested: str,
    device_used: str,
    source_mode: str,
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
    max_wall_clock_ms: float | None,
    live_timeout_s: float,
    live_command: list[str],
) -> dict[str, Any]:
    wall_clock_ms = max(0.0, wall_clock_ms)
    wall_clock_ms_per_chunk = wall_clock_ms / chunk_duration_s if chunk_duration_s > 0 else 0.0
    throughput_chunks_per_second = 0.0 if wall_clock_ms_per_chunk <= 0 else 1000.0 / wall_clock_ms_per_chunk
    return {
        "input": input_path,
        "output_dir": str(output_dir),
        "live_artifact_path": str(live_artifact_path),
        "chunk_duration_s": chunk_duration_s,
        "wall_clock_ms": round(wall_clock_ms, 6),
        "wall_clock_ms_per_chunk": round(wall_clock_ms_per_chunk, 6),
        "throughput_chunks_per_second": round(throughput_chunks_per_second, 6),
        "device_requested": device_requested,
        "device_used": device_used,
        "source_mode": source_mode,
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
            "max_wall_clock_ms": max_wall_clock_ms,
            "live_command": live_command,
            "device_requested": device_requested,
            "device_used": device_used,
            "source_mode": source_mode,
        },
    }


def _build_failure_payload(
    *,
    input_path: str,
    output_dir: Path,
    live_artifact_path: Path,
    chunk_duration_s: float,
    wall_clock_ms: float,
    device_requested: str,
    device_used: str,
    source_mode: str,
    phase: str,
    error_message: str,
    stderr: str,
    live_cli_exit_code: int | None,
    live_runtime_status: str | None,
    live_runtime_error_stage: str | None,
    live_runtime_error_message: str | None,
    clock_source: str,
    max_wall_clock_ms: float | None,
    live_timeout_s: float,
    live_command: list[str],
) -> dict[str, Any]:
    payload = _build_result_payload(
        input_path=input_path,
        output_dir=output_dir,
        live_artifact_path=live_artifact_path,
        chunk_duration_s=chunk_duration_s,
        wall_clock_ms=wall_clock_ms,
        device_requested=device_requested,
        device_used=device_used,
        source_mode=source_mode,
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
        max_wall_clock_ms=max_wall_clock_ms,
        live_timeout_s=live_timeout_s,
        live_command=live_command,
    )
    return payload


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


def run_live_throughput_benchmark(
    *,
    input_path: Path | None,
    output_dir: Path,
    artifact_path: Path | None = None,
    live_artifact_path: Path | None = None,
    source_mode: str = "mp3",
    device_requested: str = "cpu",
    device_used: str = "cpu",
    mode: str = "smoke",
    chunk_duration_s: float = DEFAULT_CHUNK_DURATION_S,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    max_queue_depth: int = DEFAULT_MAX_QUEUE_DEPTH,
    decode_timeout_s: float = DEFAULT_DECODE_TIMEOUT_S,
    model_path: str = DEFAULT_MODEL_PATH,
    mic_backend: str = "sounddevice",
    mic_device: str = "default",
    capture_duration_s: float = DEFAULT_MIC_CAPTURE_DURATION_S,
    max_wall_clock_ms: float | None = None,
    live_timeout_s: float = DEFAULT_LIVE_TIMEOUT_S,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[dict[str, Any], int]:
    if chunk_duration_s <= 0:
        raise ValueError("chunk_duration_s must be positive")
    if source_mode != "mic" and input_path is None:
        raise ValueError("input_path is required unless source_mode is mic")

    output_dir = Path(output_dir)
    artifact_path = Path(artifact_path) if artifact_path is not None else output_dir / DEFAULT_ARTIFACT_NAME
    live_artifact_path = (
        Path(live_artifact_path) if live_artifact_path is not None else output_dir / DEFAULT_LIVE_ARTIFACT_NAME
    )
    _ensure_child_path(output_dir, artifact_path, "artifact_path")
    _ensure_child_path(output_dir, live_artifact_path, "live_artifact_path")

    output_dir.mkdir(parents=True, exist_ok=True)

    live_command = _build_live_command(
        input_path=input_path,
        output_dir=output_dir,
        live_artifact_path=live_artifact_path,
        source_mode=source_mode,
        device_requested=device_requested,
        device_used=device_used,
        mode=mode,
        chunk_duration_s=chunk_duration_s,
        sample_rate_hz=sample_rate_hz,
        max_queue_depth=max_queue_depth,
        decode_timeout_s=decode_timeout_s,
        model_path=model_path,
        mic_backend=mic_backend,
        mic_device=mic_device,
        capture_duration_s=capture_duration_s,
    )

    completed, wall_clock_ms, timeout_message = _run_live_cli(
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

    if completed is not None:
        stderr = completed.stderr or ""
        live_cli_exit_code = completed.returncode

        if live_artifact_path.exists():
            try:
                live_payload = _load_and_validate_live_artifact(live_artifact_path)
            except FileNotFoundError as exc:
                failure_payload = _build_failure_payload(
                    input_path=str(input_path) if input_path is not None else mic_device,
                    output_dir=output_dir,
                    live_artifact_path=live_artifact_path,
                    chunk_duration_s=chunk_duration_s,
                    wall_clock_ms=wall_clock_ms,
                    device_requested=device_requested,
                    device_used=device_used,
                    source_mode=source_mode,
                    phase="missing_runtime_artifact",
                    error_message=str(exc),
                    stderr=stderr,
                    live_cli_exit_code=live_cli_exit_code,
                    live_runtime_status=None,
                    live_runtime_error_stage=None,
                    live_runtime_error_message=None,
                    clock_source="perf_counter",
                    max_wall_clock_ms=max_wall_clock_ms,
                    live_timeout_s=live_timeout_s,
                    live_command=live_command,
                )
                _write_json(artifact_path, failure_payload)
                print(
                    f"throughput_benchmark_failed[missing_runtime_artifact]: {exc}",
                    file=sys.stderr,
                )
                return failure_payload, 1
            except ValueError as exc:
                failure_payload = _build_failure_payload(
                    input_path=str(input_path) if input_path is not None else mic_device,
                    output_dir=output_dir,
                    live_artifact_path=live_artifact_path,
                    chunk_duration_s=chunk_duration_s,
                    wall_clock_ms=wall_clock_ms,
                    device_requested=device_requested,
                    device_used=device_used,
                    source_mode=source_mode,
                    phase="malformed_runtime_artifact",
                    error_message=str(exc),
                    stderr=stderr,
                    live_cli_exit_code=live_cli_exit_code,
                    live_runtime_status=None,
                    live_runtime_error_stage=None,
                    live_runtime_error_message=None,
                    clock_source="perf_counter",
                    max_wall_clock_ms=max_wall_clock_ms,
                    live_timeout_s=live_timeout_s,
                    live_command=live_command,
                )
                _write_json(artifact_path, failure_payload)
                print(
                    f"throughput_benchmark_failed[malformed_runtime_artifact]: {exc}",
                    file=sys.stderr,
                )
                return failure_payload, 1
            except ValidationError as exc:
                failure_payload = _build_failure_payload(
                    input_path=str(input_path) if input_path is not None else mic_device,
                    output_dir=output_dir,
                    live_artifact_path=live_artifact_path,
                    chunk_duration_s=chunk_duration_s,
                    wall_clock_ms=wall_clock_ms,
                    device_requested=device_requested,
                    device_used=device_used,
                    source_mode=source_mode,
                    phase="invalid_runtime_payload",
                    error_message=str(exc),
                    stderr=stderr,
                    live_cli_exit_code=live_cli_exit_code,
                    live_runtime_status=None,
                    live_runtime_error_stage=None,
                    live_runtime_error_message=None,
                    clock_source="perf_counter",
                    max_wall_clock_ms=max_wall_clock_ms,
                    live_timeout_s=live_timeout_s,
                    live_command=live_command,
                )
                _write_json(artifact_path, failure_payload)
                print(
                    f"throughput_benchmark_failed[invalid_runtime_payload]: {exc}",
                    file=sys.stderr,
                )
                return failure_payload, 1
            else:
                live_runtime_status = str(live_payload.get("status")) if live_payload.get("status") is not None else None
                live_runtime_error_stage = (
                    str(live_payload.get("error_stage")) if live_payload.get("error_stage") is not None else None
                )
                live_runtime_error_message = (
                    str(live_payload.get("error_message")) if live_payload.get("error_message") is not None else None
                )
        elif completed.returncode == 0:
            failure_payload = _build_failure_payload(
                input_path=str(input_path) if input_path is not None else mic_device,
                output_dir=output_dir,
                live_artifact_path=live_artifact_path,
                chunk_duration_s=chunk_duration_s,
                wall_clock_ms=wall_clock_ms,
                device_requested=device_requested,
                device_used=device_used,
                source_mode=source_mode,
                phase="missing_runtime_artifact",
                error_message=f"expected live runtime artifact was not created: {live_artifact_path}",
                stderr=stderr,
                live_cli_exit_code=live_cli_exit_code,
                live_runtime_status=None,
                live_runtime_error_stage=None,
                live_runtime_error_message=None,
                clock_source="perf_counter",
                max_wall_clock_ms=max_wall_clock_ms,
                live_timeout_s=live_timeout_s,
                live_command=live_command,
            )
            _write_json(artifact_path, failure_payload)
            print(
                f"throughput_benchmark_failed[missing_runtime_artifact]: {live_artifact_path}",
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
                input_path=str(input_path) if input_path is not None else mic_device,
                output_dir=output_dir,
                live_artifact_path=live_artifact_path,
                chunk_duration_s=chunk_duration_s,
                wall_clock_ms=wall_clock_ms,
                device_requested=device_requested,
                device_used=device_used,
                source_mode=source_mode,
                phase=failure_stage,
                error_message=failure_message,
                stderr=stderr,
                live_cli_exit_code=live_cli_exit_code,
                live_runtime_status=live_runtime_status,
                live_runtime_error_stage=live_runtime_error_stage,
                live_runtime_error_message=live_runtime_error_message,
                clock_source="perf_counter",
                max_wall_clock_ms=max_wall_clock_ms,
                live_timeout_s=live_timeout_s,
                live_command=live_command,
            )
            _write_json(artifact_path, failure_payload)
            print(
                f"throughput_benchmark_failed[{failure_stage}]: {failure_message}",
                file=sys.stderr,
            )
            return failure_payload, 1

    else:
        failure_payload = _build_failure_payload(
            input_path=str(input_path) if input_path is not None else mic_device,
            output_dir=output_dir,
            live_artifact_path=live_artifact_path,
            chunk_duration_s=chunk_duration_s,
            wall_clock_ms=wall_clock_ms,
            device_requested=device_requested,
            device_used=device_used,
            source_mode=source_mode,
            phase="live_cli_timeout",
            error_message=timeout_message or "live CLI timed out",
            stderr="",
            live_cli_exit_code=None,
            live_runtime_status=None,
            live_runtime_error_stage=None,
            live_runtime_error_message=None,
            clock_source="perf_counter",
            max_wall_clock_ms=max_wall_clock_ms,
            live_timeout_s=live_timeout_s,
            live_command=live_command,
        )
        _write_json(artifact_path, failure_payload)
        print(
            f"throughput_benchmark_failed[live_cli_timeout]: {timeout_message}",
            file=sys.stderr,
        )
        return failure_payload, 1

    if live_runtime_status != "ok":
        failure_stage = "live_runtime_failed"
        failure_message = f"live runtime reported status={live_runtime_status or 'unknown'}"
        if live_runtime_error_stage:
            failure_message = f"live runtime reported {live_runtime_error_stage}: {live_runtime_error_message or 'no error message'}"
        failure_payload = _build_failure_payload(
            input_path=str(input_path) if input_path is not None else mic_device,
            output_dir=output_dir,
            live_artifact_path=live_artifact_path,
            chunk_duration_s=chunk_duration_s,
            wall_clock_ms=wall_clock_ms,
            device_requested=device_requested,
            device_used=device_used,
            source_mode=source_mode,
            phase=failure_stage,
            error_message=failure_message,
            stderr=stderr,
            live_cli_exit_code=live_cli_exit_code,
            live_runtime_status=live_runtime_status,
            live_runtime_error_stage=live_runtime_error_stage,
            live_runtime_error_message=live_runtime_error_message,
            clock_source="perf_counter",
            max_wall_clock_ms=max_wall_clock_ms,
            live_timeout_s=live_timeout_s,
            live_command=live_command,
        )
        _write_json(artifact_path, failure_payload)
        print(
            f"throughput_benchmark_failed[{failure_stage}]: {failure_message}",
            file=sys.stderr,
        )
        return failure_payload, 1

    budget_breached = max_wall_clock_ms is not None and wall_clock_ms > max_wall_clock_ms
    status = "error" if budget_breached else "ok"
    phase = "throughput_budget_exceeded" if budget_breached else "complete"
    error_stage = phase if budget_breached else None
    error_message = (
        f"wall-clock throughput budget exceeded: {wall_clock_ms:.3f}ms > {max_wall_clock_ms:.3f}ms"
        if budget_breached
        else None
    )
    result_payload = _build_result_payload(
        input_path=str(input_path) if input_path is not None else mic_device,
        output_dir=output_dir,
        live_artifact_path=live_artifact_path,
        chunk_duration_s=chunk_duration_s,
        wall_clock_ms=wall_clock_ms,
        device_requested=device_requested,
        device_used=device_used,
        source_mode=source_mode,
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
        max_wall_clock_ms=max_wall_clock_ms,
        live_timeout_s=live_timeout_s,
        live_command=live_command,
    )
    _write_json(artifact_path, result_payload)

    if budget_breached:
        print(
            f"throughput_benchmark_failed[throughput_budget_exceeded]: {error_message}",
            file=sys.stderr,
        )
        return result_payload, 1

    print(f"live_throughput_artifact: {artifact_path}")
    return result_payload, 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure live separation throughput with a real subprocess run.")
    parser.add_argument("--input", type=Path, default=None, help="Path to the source audio/video fixture.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory that will contain the throughput and live runtime artifacts.",
    )
    parser.add_argument(
        "--artifact-path",
        type=Path,
        default=None,
        help="Path for the throughput artifact. Defaults to <output-dir>/live_throughput_result.json.",
    )
    parser.add_argument(
        "--live-artifact-path",
        type=Path,
        default=None,
        help="Path for the live runtime artifact. Defaults to <output-dir>/live_runtime_result.json.",
    )
    parser.add_argument(
        "--source-mode",
        choices=["mp3", "video-audio", "mic"],
        default="mp3",
        help="Source mode forwarded to the live runtime CLI.",
    )
    parser.add_argument(
        "--device-requested",
        choices=["cpu", "gpu"],
        default="cpu",
        help="Requested device label recorded in the benchmark artifact.",
    )
    parser.add_argument(
        "--device-used",
        choices=["cpu", "gpu"],
        default="cpu",
        help="Actual device label recorded in the benchmark artifact.",
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
        help="Chunk duration to pass through to the live runtime.",
    )
    parser.add_argument(
        "--sample-rate-hz",
        type=int,
        default=DEFAULT_SAMPLE_RATE_HZ,
        help="Target sample rate passed to the live runtime.",
    )
    parser.add_argument(
        "--max-queue-depth",
        type=int,
        default=DEFAULT_MAX_QUEUE_DEPTH,
        help="Maximum queue depth passed to the live runtime.",
    )
    parser.add_argument(
        "--decode-timeout-s",
        type=float,
        default=DEFAULT_DECODE_TIMEOUT_S,
        help="Decode timeout passed to the live runtime.",
    )
    parser.add_argument(
        "--model-path",
        default=DEFAULT_MODEL_PATH,
        help="Model path passed to the live runtime.",
    )
    parser.add_argument(
        "--mic-backend",
        choices=["fake", "sounddevice"],
        default="sounddevice",
        help="Microphone backend forwarded when --source-mode mic is selected.",
    )
    parser.add_argument(
        "--mic-device",
        default="default",
        help="Microphone device forwarded when --source-mode mic is selected.",
    )
    parser.add_argument(
        "--capture-duration-s",
        type=float,
        default=DEFAULT_MIC_CAPTURE_DURATION_S,
        help="Microphone capture duration forwarded when --source-mode mic is selected.",
    )
    parser.add_argument(
        "--max-wall-clock-ms",
        type=float,
        default=None,
        help="Optional wall-clock budget for the 1-second throughput run.",
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
        _, exit_code = run_live_throughput_benchmark(
            input_path=args.input,
            output_dir=args.output_dir,
            artifact_path=args.artifact_path,
            live_artifact_path=args.live_artifact_path,
            source_mode=str(args.source_mode),
            device_requested=str(args.device_requested),
            device_used=str(args.device_used),
            mode=str(args.mode),
            chunk_duration_s=float(args.chunk_duration_s),
            sample_rate_hz=int(args.sample_rate_hz),
            max_queue_depth=int(args.max_queue_depth),
            decode_timeout_s=float(args.decode_timeout_s),
            model_path=str(args.model_path),
            mic_backend=str(args.mic_backend),
            mic_device=str(args.mic_device),
            capture_duration_s=float(args.capture_duration_s),
            max_wall_clock_ms=args.max_wall_clock_ms,
            live_timeout_s=float(args.live_timeout_s),
        )
        return exit_code
    except (ValueError, FileNotFoundError) as exc:
        print(f"throughput_benchmark_config_error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover
        print(f"throughput_benchmark_failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
