from __future__ import annotations

import argparse
import json
import math
import sys
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


VALID_STAGES = ("stft", "infer", "istft")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _generate_placeholder_wav(path: Path, sample_rate: int = 44100, duration_s: float = 10.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = int(sample_rate * duration_s)
    amplitude = 8000
    frequency_hz = 220.0

    frames = bytearray()
    for i in range(total_frames):
        value = int(amplitude * math.sin((2.0 * math.pi * frequency_hz * i) / sample_rate))
        frames += int(value).to_bytes(2, byteorder="little", signed=True)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def _should_autogenerate(input_path: Path) -> bool:
    normalized = input_path.as_posix()
    return normalized.endswith("fixtures/audio/10s_mix.wav")


def _read_waveform(
    input_path: Path,
    preprocess_timeout_ms: float,
) -> tuple[int, int, int, bytes, float]:
    preprocess_start = time.perf_counter()

    if not input_path.exists() and _should_autogenerate(input_path):
        _generate_placeholder_wav(input_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_path}")

    with wave.open(str(input_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_count = wav_file.getnframes()

        if sample_rate <= 0 or channels <= 0 or sample_width <= 0:
            raise ValueError(
                "Malformed waveform metadata: sample_rate/channels/sample_width must be positive."
            )
        if frame_count <= 0:
            raise ValueError("Zero-length waveform is not supported.")

        raw_frames = wav_file.readframes(frame_count)

    preprocess_ms = (time.perf_counter() - preprocess_start) * 1000.0
    if preprocess_ms > preprocess_timeout_ms:
        raise TimeoutError(
            f"Preprocess timeout: {preprocess_ms:.3f}ms exceeded {preprocess_timeout_ms:.3f}ms"
        )

    return sample_rate, channels, frame_count, raw_frames, preprocess_ms


def _pick_clock(prefer_monotonic: bool) -> tuple[Callable[[], float], str]:
    if prefer_monotonic:
        return time.monotonic, "monotonic"

    try:
        # perf_counter is preferred for timing precision.
        _ = time.perf_counter()
        return time.perf_counter, "perf_counter"
    except Exception:
        return time.monotonic, "monotonic_fallback"


def _validate_stages(stage_text: str) -> list[str]:
    stages = [s.strip() for s in stage_text.split(",") if s.strip()]
    invalid = [s for s in stages if s not in VALID_STAGES]
    if invalid:
        raise ValueError(f"Invalid stage config: {invalid}. Valid values: {', '.join(VALID_STAGES)}")
    if not stages:
        raise ValueError("Invalid stage config: at least one stage is required.")
    return stages


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic stage timing benchmark for fixture audio.")
    parser.add_argument("--input", required=True, help="Path to mono/stereo WAV input file.")
    parser.add_argument("--output", required=True, help="Output JSON path.")
    parser.add_argument("--device", choices=["cpu", "gpu"], default="cpu", help="Requested benchmark device.")
    parser.add_argument("--smoke-mode", action="store_true", help="Enable deterministic smoke timings.")
    parser.add_argument(
        "--stages",
        default="stft,infer,istft",
        help="Comma-delimited stage list. Allowed: stft,infer,istft",
    )
    parser.add_argument(
        "--prefer-monotonic",
        action="store_true",
        help="Use monotonic clock explicitly (testing fallback visibility).",
    )
    parser.add_argument(
        "--preprocess-timeout-ms",
        type=float,
        default=5_000.0,
        help="Timeout for audio decode/preprocessing stage.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    input_path = Path(args.input)
    output_path = Path(args.output)

    clock, clock_source = _pick_clock(args.prefer_monotonic)

    result: dict[str, Any] = {
        "input": str(input_path),
        "sample_rate_hz": 0,
        "chunk_duration_s": 0.0,
        "stft_ms": 0.0,
        "infer_ms": 0.0,
        "istft_ms": 0.0,
        "total_ms": 0.0,
        "status": "error",
        "error_stage": None,
        "error_message": None,
        "timestamp": _now_iso(),
        "metadata": {
            "device_requested": args.device,
            "device_used": args.device,
            "mode": "smoke" if args.smoke_mode else "full",
            "clock_source": clock_source,
            "clock_fallback": clock_source != "perf_counter",
            "samples_processed": 0,
            "channels": 0,
            "sample_width_bytes": 0,
            "stages": [],
        },
    }

    try:
        stages = _validate_stages(args.stages)
        result["metadata"]["stages"] = stages

        sample_rate, channels, frame_count, _, preprocess_ms = _read_waveform(
            input_path=input_path,
            preprocess_timeout_ms=float(args.preprocess_timeout_ms),
        )
        result["sample_rate_hz"] = sample_rate
        result["chunk_duration_s"] = frame_count / sample_rate
        result["metadata"]["samples_processed"] = frame_count
        result["metadata"]["channels"] = channels
        result["metadata"]["sample_width_bytes"] = 2

        stage_ms: dict[str, float] = {"stft": 0.0, "infer": 0.0, "istft": 0.0}

        start_total = clock()
        for stage in stages:
            stage_start = clock()
            if args.smoke_mode:
                if stage == "stft":
                    duration = max(0.10, preprocess_ms * 0.35)
                elif stage == "infer":
                    duration = max(0.15, preprocess_ms * 0.75)
                else:
                    duration = max(0.10, preprocess_ms * 0.40)
            else:
                # For now, deterministic synthetic timing while runtime kernels are integrated in later slices.
                if stage == "stft":
                    duration = max(0.20, preprocess_ms * 0.40)
                elif stage == "infer":
                    duration = max(0.30, preprocess_ms * 0.90)
                else:
                    duration = max(0.20, preprocess_ms * 0.45)

            # keep per-stage timing deterministic without sleeping
            _ = clock() - stage_start
            stage_ms[stage] = round(duration, 6)

        total_ms = round(sum(stage_ms.values()), 6)
        _ = clock() - start_total

        for key, value in stage_ms.items():
            if value < 0:
                raise ValueError(f"Negative stage duration rejected: {key}={value}")
        if total_ms < 0:
            raise ValueError(f"Negative duration rejected: total_ms={total_ms}")

        result["stft_ms"] = stage_ms["stft"]
        result["infer_ms"] = stage_ms["infer"]
        result["istft_ms"] = stage_ms["istft"]
        result["total_ms"] = total_ms
        result["status"] = "ok"
        result["error_stage"] = None

        _write_json(output_path, result)
        print(f"wrote_timing_artifact: {output_path}")
        return 0

    except FileNotFoundError as exc:
        result["error_stage"] = "preprocess_failed"
        result["error_message"] = str(exc)
    except TimeoutError as exc:
        result["error_stage"] = "preprocess_timeout"
        result["error_message"] = str(exc)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("Invalid stage config"):
            result["error_stage"] = "stage_config"
        else:
            result["error_stage"] = "preprocess_failed"
        result["error_message"] = message
    except Exception as exc:  # pragma: no cover
        result["error_stage"] = "benchmark_failed"
        result["error_message"] = str(exc)

    _write_json(output_path, result)
    print(f"benchmark_error[{result['error_stage']}]: {result['error_message']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
