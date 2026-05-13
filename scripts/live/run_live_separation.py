from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from live_runtime.contracts import LiveRuntimeResult, SourceDescriptor, StageTimings, validate_live_runtime_result
from live_runtime.live_core import DEFAULT_MODEL_PATH, build_live_runtime_result, resolve_live_model_path
from live_runtime.mp3_ingest import (
    DecodeFailedError,
    DecodeTimeoutError,
    decode_audio_to_pcm,
)
from live_runtime.mic_ingest import (
    DEFAULT_MIC_CAPTURE_DURATION_S,
    FakeMicCaptureBackend,
    MicCaptureFailedError,
    MicCaptureTimeoutError,
    SoundDeviceMicCaptureBackend,
    build_mic_source_descriptor,
    build_mic_source_ingest,
)
from live_runtime.source_ingest import (
    SourceIngestEnvelope,
    build_mp3_source_descriptor,
    build_source_ingest,
)
from live_runtime.stem_router import (
    StemRoutingError,
    resolve_live_stem_routing,
    write_live_mix_wav,
    write_live_stems,
    write_live_stems_from_arrays,
)
from live_runtime.video_ingest import build_video_source_descriptor

DEFAULT_MP3_INPUT_PATH = PROJECT_ROOT / "fixtures/audio/demo_mix.mp3"
DEFAULT_VIDEO_INPUT_PATH = PROJECT_ROOT / "fixtures/video/demo_mix.mp4"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts/live/smoke"
DEFAULT_ARTIFACT_NAME = "live_runtime_result.json"
DEFAULT_SAMPLE_RATE_HZ = 22050
DEFAULT_CHUNK_DURATION_S = 0.5
DEFAULT_DECODE_TIMEOUT_S = 30.0
DEFAULT_MAX_QUEUE_DEPTH = 64
DEFAULT_SOURCE_MODE = "mp3"
DEFAULT_MIC_DEVICE = "default"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_umx_runtime() -> Any:
    try:
        from live_runtime import umx_separator
    except ImportError as exc:  # pragma: no cover - depends on optional runtime extra
        raise RuntimeError(
            "Full mode requires optional GPU dependencies: numpy, torch, torchaudio, openunmix. "
            "Install the project with the gpu extra and rerun with --mode full."
        ) from exc

    if not umx_separator.is_available():
        raise RuntimeError(
            "Full mode requires optional GPU dependencies: torch, torchaudio, openunmix. "
            "Install the project with the gpu extra and rerun with --mode full."
        )

    return umx_separator


def _resolve_input_path(source_mode: str, input_path: Path | None) -> Path:
    if input_path is not None:
        return input_path
    if source_mode == "video-audio":
        return DEFAULT_VIDEO_INPUT_PATH
    return DEFAULT_MP3_INPUT_PATH


def _build_source_descriptor(
    *,
    source_mode: str,
    input_path: Path | None,
    mic_device: str,
    mic_backend: str,
    capture_duration_s: float,
    sample_rate_hz: int,
) -> SourceDescriptor:
    resolved_input = _resolve_input_path(source_mode, input_path)
    if source_mode == "video-audio":
        return build_video_source_descriptor(resolved_input)
    if source_mode == "mic":
        return build_mic_source_descriptor(
            mic_device,
            backend_name=mic_backend,
            capture_duration_s=capture_duration_s,
            sample_rate_hz=sample_rate_hz,
        )
    return build_mp3_source_descriptor(resolved_input)


def _build_failure_payload(
    *,
    source: SourceDescriptor,
    input_reference: str,
    output_dir: Path,
    sample_rate_hz: int,
    chunk_duration_s: float,
    device_requested: str,
    device_used: str,
    mode: str,
    requested_model_path: str,
    model_path: str,
    fallback_applied: bool,
    error_stage: str,
    error_message: str,
) -> dict[str, Any]:
    return {
        "source": source.to_dict(),
        "input": input_reference,
        "sample_rate_hz": sample_rate_hz,
        "chunk_duration_s": chunk_duration_s,
        "chunk_index": 0,
        "stft_ms": 0.0,
        "infer_ms": 0.0,
        "istft_ms": 0.0,
        "total_ms": 0.0,
        "status": "error",
        "error_stage": error_stage,
        "error_message": error_message,
        "timestamp": _now_iso(),
        "health_state": "degraded",
        "health_reason": error_message or error_stage or "runtime failed",
        "requested_model_path": requested_model_path,
        "fallback_applied": fallback_applied,
        "queue_depth": 0,
        "drop_count": 0,
        "model_path": model_path,
        "stem_paths": {
            "vocals": str(output_dir / "vocals.wav"),
            "drums": str(output_dir / "drums.wav"),
            "bass": str(output_dir / "bass.wav"),
            "other": str(output_dir / "other.wav"),
        },
        "metadata": {
            "device_requested": device_requested,
            "device_used": device_used,
            "mode": mode,
            "clock_source": "ingest",
            "clock_fallback": False,
            "samples_processed": 0,
            "channels": 0,
            "sample_width_bytes": 0,
            "stages": ["stft", "infer", "istft"],
        },
    }


def _build_artifact(
    *,
    source_mode: str,
    input_path: Path | None,
    output_dir: Path,
    sample_rate_hz: int,
    chunk_duration_s: float,
    max_queue_depth: int | None,
    decode_timeout_s: float,
    device_requested: str,
    device_used: str,
    mode: str,
    model_path: str,
    mic_backend: str,
    mic_device: str,
    capture_duration_s: float,
) -> tuple[dict[str, Any], int, SourceIngestEnvelope | None]:
    source_descriptor = _build_source_descriptor(
        source_mode=source_mode,
        input_path=input_path,
        mic_device=mic_device,
        mic_backend=mic_backend,
        capture_duration_s=capture_duration_s,
        sample_rate_hz=sample_rate_hz,
    )
    resolved_input = _resolve_input_path(source_mode, input_path)
    model_resolution = resolve_live_model_path(model_path)

    try:
        if source_mode == "video-audio":
            ingest = build_source_ingest(
                source_descriptor,
                decode_audio=decode_audio_to_pcm,
                target_sample_rate_hz=sample_rate_hz,
                chunk_duration_s=chunk_duration_s,
                decode_timeout_s=decode_timeout_s,
                max_queue_depth=max_queue_depth,
            )
        elif source_mode == "mic":
            backend = (
                FakeMicCaptureBackend()
                if mic_backend == "fake"
                else SoundDeviceMicCaptureBackend()
            )
            ingest = build_mic_source_ingest(
                mic_device,
                backend=backend,
                target_sample_rate_hz=sample_rate_hz,
                chunk_duration_s=chunk_duration_s,
                capture_duration_s=capture_duration_s,
                capture_timeout_s=decode_timeout_s,
                max_queue_depth=max_queue_depth,
            )
        else:
            ingest = build_source_ingest(
                source_descriptor,
                decode_audio=decode_audio_to_pcm,
                target_sample_rate_hz=sample_rate_hz,
                chunk_duration_s=chunk_duration_s,
                decode_timeout_s=decode_timeout_s,
                max_queue_depth=max_queue_depth,
            )
    except (FileNotFoundError, DecodeFailedError, DecodeTimeoutError) as exc:
        error_stage = getattr(exc, "error_stage", "decode_failed")
        error_message = getattr(exc, "message", str(exc))
        payload = _build_failure_payload(
            source=source_descriptor,
            input_reference=str(resolved_input),
            output_dir=output_dir,
            sample_rate_hz=sample_rate_hz,
            chunk_duration_s=chunk_duration_s,
            device_requested=device_requested,
            device_used=device_used,
            mode=mode,
            requested_model_path=model_resolution.requested_model_path,
            model_path=model_resolution.model_path,
            fallback_applied=model_resolution.fallback_applied,
            error_stage=error_stage,
            error_message=error_message,
        )
        validate_live_runtime_result(payload)
        return payload, 1, None
    except (MicCaptureFailedError, MicCaptureTimeoutError) as exc:
        error_stage = getattr(exc, "error_stage", "capture_failed")
        error_message = getattr(exc, "message", str(exc))
        payload = _build_failure_payload(
            source=source_descriptor,
            input_reference=mic_device,
            output_dir=output_dir,
            sample_rate_hz=sample_rate_hz,
            chunk_duration_s=chunk_duration_s,
            device_requested=device_requested,
            device_used=device_used,
            mode=mode,
            requested_model_path=model_resolution.requested_model_path,
            model_path=model_resolution.model_path,
            fallback_applied=model_resolution.fallback_applied,
            error_stage=error_stage,
            error_message=error_message,
        )
        validate_live_runtime_result(payload)
        return payload, 1, None
    except Exception as exc:
        payload = _build_failure_payload(
            source=source_descriptor,
            input_reference=mic_device if source_mode == "mic" else str(resolved_input),
            output_dir=output_dir,
            sample_rate_hz=sample_rate_hz,
            chunk_duration_s=chunk_duration_s,
            device_requested=device_requested,
            device_used=device_used,
            mode=mode,
            requested_model_path=model_resolution.requested_model_path,
            model_path=model_resolution.model_path,
            fallback_applied=model_resolution.fallback_applied,
            error_stage="live_cli_failed",
            error_message=str(exc),
        )
        validate_live_runtime_result(payload)
        return payload, 1, None

    routing = resolve_live_stem_routing(output_dir)

    stage_timings_override: StageTimings | None = None
    separation_result = None
    if mode == "full":
        try:
            umx_runtime = _load_umx_runtime()
            actual_device = umx_runtime.resolve_device(device_requested)
            separator = umx_runtime.load_umxhq_separator(actual_device)
            audio_tensor = umx_runtime.pcm_to_tensor(ingest.decoded_audio.pcm)
            separation_result = umx_runtime.separate_tensor(
                audio_tensor,
                ingest.decoded_audio.sample_rate_hz,
                separator,
                actual_device,
            )
            t = separation_result.timings
            stage_timings_override = StageTimings(
                stft_ms=t.stft_ms,
                infer_ms=t.infer_ms,
                istft_ms=t.istft_ms,
                total_ms=t.total_ms,
            )
            device_used = "gpu" if actual_device == "cuda" else actual_device
        except Exception as exc:
            payload = _build_failure_payload(
                source=source_descriptor,
                input_reference=mic_device if source_mode == "mic" else str(resolved_input),
                output_dir=output_dir,
                sample_rate_hz=sample_rate_hz,
                chunk_duration_s=chunk_duration_s,
                device_requested=device_requested,
                device_used=device_used,
                mode=mode,
                requested_model_path=model_resolution.requested_model_path,
                model_path=model_resolution.model_path,
                fallback_applied=model_resolution.fallback_applied,
                error_stage="model_load_failed",
                error_message=str(exc),
            )
            validate_live_runtime_result(payload)
            return payload, 1, None

    result: LiveRuntimeResult = build_live_runtime_result(
        ingest,
        chunk_duration_s=chunk_duration_s,
        target_sample_rate_hz=sample_rate_hz,
        max_queue_depth=max_queue_depth,
        decode_timeout_s=decode_timeout_s,
        device_requested=device_requested,
        device_used=device_used,
        mode=mode,
        model_path=model_resolution.requested_model_path,
        stem_routing=routing,
        stage_timings_override=stage_timings_override,
    )

    payload = result.to_dict()
    validate_live_runtime_result(payload)
    return payload, 0, (ingest, separation_result)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the live smoke separation flow and emit a JSON runtime artifact, mix.wav "
        "(decoded source), plus four stem WAVs.",
    )
    parser.add_argument(
        "--source-mode",
        choices=["mp3", "video-audio", "mic"],
        default=DEFAULT_SOURCE_MODE,
        help="Source mode for the live ingest path.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to the MP3 or video source. Defaults to the mode-specific fixture when omitted.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for mix.wav plus the four stem outputs.",
    )
    parser.add_argument(
        "--artifact-path",
        type=Path,
        default=None,
        help="Path for the live runtime JSON artifact. Defaults to <output-dir>/live_runtime_result.json.",
    )
    parser.add_argument(
        "--sample-rate-hz",
        type=int,
        default=DEFAULT_SAMPLE_RATE_HZ,
        help="Target sample rate for live decode and output stems.",
    )
    parser.add_argument(
        "--chunk-duration-s",
        type=float,
        default=DEFAULT_CHUNK_DURATION_S,
        help="Chunk duration used by the live ingest core.",
    )
    parser.add_argument(
        "--decode-timeout-s",
        type=float,
        default=DEFAULT_DECODE_TIMEOUT_S,
        help="Timeout for source decode or capture before the run fails.",
    )
    parser.add_argument(
        "--max-queue-depth",
        type=int,
        default=DEFAULT_MAX_QUEUE_DEPTH,
        help="Maximum queue depth to report before backpressure is considered exhausted.",
    )
    parser.add_argument(
        "--device-requested",
        choices=["cpu", "gpu"],
        default="cpu",
        help="Requested runtime device recorded in the artifact.",
    )
    parser.add_argument(
        "--device-used",
        choices=["cpu", "gpu"],
        default="cpu",
        help="Actual runtime device recorded in the artifact.",
    )
    parser.add_argument(
        "--mode",
        choices=["smoke", "full"],
        default="smoke",
        help="Runtime mode recorded in the artifact.",
    )
    parser.add_argument(
        "--model-path",
        default=DEFAULT_MODEL_PATH,
        help="Model path recorded in the artifact.",
    )
    parser.add_argument(
        "--mic-backend",
        choices=["fake", "sounddevice"],
        default="sounddevice",
        help="Microphone capture backend used when --source-mode mic is selected.",
    )
    parser.add_argument(
        "--mic-device",
        default=DEFAULT_MIC_DEVICE,
        help="Microphone device identifier recorded in the artifact.",
    )
    parser.add_argument(
        "--capture-duration-s",
        type=float,
        default=DEFAULT_MIC_CAPTURE_DURATION_S,
        help="Microphone capture window used when --source-mode mic is selected.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    artifact_path = args.artifact_path or (args.output_dir / DEFAULT_ARTIFACT_NAME)
    input_path = Path(args.input) if args.input is not None else None
    output_dir = Path(args.output_dir)

    result_payload: dict[str, Any] | None = None
    ingest_result = None
    exit_code = 0

    try:
        result_payload, exit_code, ingest_result = _build_artifact(
            source_mode=str(args.source_mode),
            input_path=input_path,
            output_dir=output_dir,
            sample_rate_hz=int(args.sample_rate_hz),
            chunk_duration_s=float(args.chunk_duration_s),
            max_queue_depth=args.max_queue_depth,
            decode_timeout_s=float(args.decode_timeout_s),
            device_requested=str(args.device_requested),
            device_used=str(args.device_used),
            mode=str(args.mode),
            model_path=str(args.model_path),
            mic_backend=str(args.mic_backend),
            mic_device=str(args.mic_device),
            capture_duration_s=float(args.capture_duration_s),
        )

        if exit_code == 0:
            if ingest_result is None:
                raise RuntimeError("ingest result missing for successful live run")
            ingest_envelope, separation_result = ingest_result if isinstance(ingest_result, tuple) else (ingest_result, None)
            if separation_result is not None and separation_result.stems:
                write_live_stems_from_arrays(
                    separation_result.stems,
                    output_dir,
                    separation_result.sample_rate_hz,
                )
            else:
                write_live_stems(ingest_envelope, output_dir)
            write_live_mix_wav(
                output_dir,
                sample_rate_hz=int(ingest_envelope.decoded_audio.sample_rate_hz),
                pcm=ingest_envelope.decoded_audio.pcm,
            )
            _write_json_atomic(artifact_path, result_payload)
            print(f"live_runtime_artifact: {artifact_path}")
            mix_path = output_dir / "mix.wav"
            print(
                f"live_stems: {mix_path} "
                f"{output_dir / 'vocals.wav'} {output_dir / 'drums.wav'} "
                f"{output_dir / 'bass.wav'} {output_dir / 'other.wav'}",
            )
            if result_payload["health_state"] != "healthy":
                print(
                    f"live_runtime_health[{result_payload['health_state']}]: {result_payload['health_reason']}",
                    file=sys.stderr,
                )
            return exit_code

        _write_json_atomic(artifact_path, result_payload)
        return exit_code

    except StemRoutingError as exc:
        if result_payload is None:
            source = _build_source_descriptor(
                source_mode=str(args.source_mode),
                input_path=input_path,
                mic_device=str(args.mic_device),
                mic_backend=str(args.mic_backend),
                capture_duration_s=float(args.capture_duration_s),
                sample_rate_hz=int(args.sample_rate_hz),
            )
            model_resolution = resolve_live_model_path(str(args.model_path))
            result_payload = _build_failure_payload(
                source=source,
                input_reference=str(input_path or _resolve_input_path(str(args.source_mode), input_path)),
                output_dir=output_dir,
                sample_rate_hz=int(args.sample_rate_hz),
                chunk_duration_s=float(args.chunk_duration_s),
                device_requested=str(args.device_requested),
                device_used=str(args.device_used),
                mode=str(args.mode),
                requested_model_path=model_resolution.requested_model_path,
                model_path=model_resolution.model_path,
                fallback_applied=model_resolution.fallback_applied,
                error_stage=exc.error_stage,
                error_message=exc.message,
            )
        else:
            result_payload = dict(result_payload)
            result_payload["status"] = "error"
            result_payload["error_stage"] = exc.error_stage
            result_payload["error_message"] = exc.message
            result_payload["health_state"] = "degraded"
            result_payload["health_reason"] = exc.message

        validate_live_runtime_result(result_payload)
        _write_json_atomic(artifact_path, result_payload)
        print(f"live_runtime_failed[{exc.error_stage}]: {exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        if result_payload is not None:
            result_payload = dict(result_payload)
            result_payload["status"] = "error"
            result_payload["error_stage"] = "live_cli_failed"
            result_payload["error_message"] = str(exc)
            result_payload["health_state"] = "degraded"
            result_payload["health_reason"] = str(exc)
            validate_live_runtime_result(result_payload)
            _write_json_atomic(artifact_path, result_payload)
        print(f"live_cli_failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
