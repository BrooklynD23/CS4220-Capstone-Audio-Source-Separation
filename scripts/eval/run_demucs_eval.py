from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.eval.run_umx_eval import (
    _discover_tracks,
    _load_protocol,
    _simulate_model_load,
    _validate_real_track_layout,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _environment_fingerprint() -> dict[str, str | None]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "gpu_model": None,
    }


def _dry_run_track_result(track_name: str, index: int) -> dict[str, Any]:
    sdr = 5.4 + (index * 0.1)
    stft_ms = 2.5 + index
    infer_ms = 10.0 + index
    istft_ms = 3.5 + index

    return {
        "track_name": track_name,
        "model_family": "demucs",
        "targets": {"vocals": {"sdr": round(sdr, 3)}},
        "stft_ms": stft_ms,
        "infer_ms": infer_ms,
        "istft_ms": istft_ms,
        "total_ms": round(stft_ms + infer_ms + istft_ms, 3),
        "status": "ok",
        "error_stage": None,
        "timestamp": _now_iso(),
    }


def _load_demucs_runtime() -> Any:
    try:
        import torch  # type: ignore
        from demucs.apply import apply_model  # type: ignore
        from demucs.audio import convert_audio  # type: ignore
        from demucs.pretrained import get_model  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on optional runtime package
        raise RuntimeError(
            "Demucs full evaluation requires optional Demucs runtime dependencies. "
            "Install demucs and rerun without --dry-run."
        ) from exc
    return {
        "apply_model": apply_model,
        "convert_audio": convert_audio,
        "get_model": get_model,
        "torch": torch,
    }


def _read_wav_tensor(path: Path, torch: Any) -> tuple[Any, int]:
    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())

    import numpy as np

    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels == 1:
        tensor = torch.from_numpy(audio.copy()).unsqueeze(0)
    else:
        tensor = torch.from_numpy(audio.reshape(-1, channels).T.copy())
    return tensor, sample_rate


def _sdr_db(reference: Any, estimate: Any) -> float:
    import numpy as np

    ref_np = reference.detach().cpu().numpy() if hasattr(reference, "detach") else np.asarray(reference)
    est_np = estimate.detach().cpu().numpy() if hasattr(estimate, "detach") else np.asarray(estimate)
    ref_np = ref_np.mean(axis=0) if ref_np.ndim == 2 else ref_np
    est_np = est_np.mean(axis=0) if est_np.ndim == 2 else est_np
    n = min(ref_np.shape[-1], est_np.shape[-1])
    ref_np = ref_np[..., :n]
    est_np = est_np[..., :n]
    numerator = np.sum(ref_np**2)
    denominator = np.sum((ref_np - est_np) ** 2) + 1e-10
    return round(float(10.0 * np.log10(numerator / denominator + 1e-10)), 3)


def _real_track_result(track_path: Path, index: int, runtime: Any) -> dict[str, Any]:
    mix_path = _validate_real_track_layout(track_path)
    torch = runtime["torch"]
    device = "cuda" if torch.cuda.is_available() else "cpu"

    load_started = time.perf_counter()
    model = runtime["get_model"]("htdemucs").to(device)
    model.eval()
    load_ms = (time.perf_counter() - load_started) * 1000.0

    mix, sample_rate = _read_wav_tensor(mix_path, torch)
    model_sample_rate = int(getattr(model, "samplerate", sample_rate))
    model_channels = int(getattr(model, "audio_channels", mix.shape[0]))

    stft_started = time.perf_counter()
    mix = runtime["convert_audio"](mix, sample_rate, model_sample_rate, model_channels)
    stft_ms = (time.perf_counter() - stft_started) * 1000.0

    infer_started = time.perf_counter()
    with torch.no_grad():
        estimates = runtime["apply_model"](
            model,
            mix.unsqueeze(0).to(device),
            split=True,
            progress=False,
            device=device,
        )[0].cpu()
    infer_ms = (time.perf_counter() - infer_started) * 1000.0

    sources = list(getattr(model, "sources", ("drums", "bass", "other", "vocals")))
    vocals_index = sources.index("vocals") if "vocals" in sources else len(sources) - 1
    reference, reference_sample_rate = _read_wav_tensor(track_path / "vocals.wav", torch)
    if reference_sample_rate != model_sample_rate or reference.shape[0] != model_channels:
        reference = runtime["convert_audio"](
            reference,
            reference_sample_rate,
            model_sample_rate,
            model_channels,
        )

    return {
        "track_name": track_path.name,
        "model_family": "demucs",
        "targets": {"vocals": {"sdr": _sdr_db(reference, estimates[vocals_index])}},
        "stft_ms": round(stft_ms, 3),
        "infer_ms": round(load_ms + infer_ms, 3),
        "istft_ms": 0.0,
        "total_ms": round(stft_ms + load_ms + infer_ms, 3),
        "status": "ok",
        "error_stage": None,
        "timestamp": _now_iso(),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Demucs evaluation and emit per-track metrics artifacts.")
    parser.add_argument("--protocol", required=True, help="Path to evaluation protocol YAML")
    parser.add_argument("--dataset-root", required=True, help="MUSDB18 dataset root")
    parser.add_argument("--output", required=True, help="Output directory for track artifacts")
    parser.add_argument("--max-tracks", type=int, default=1, help="Maximum number of tracks to process")
    parser.add_argument("--dry-run", action="store_true", help="Skip heavy model inference and emit deterministic artifacts")
    parser.add_argument(
        "--model-timeout-s",
        type=float,
        default=30.0,
        help="Maximum time allowed for model initialization",
    )
    parser.add_argument(
        "--simulate-model-load-failure",
        action="store_true",
        help="Testing hook: force model load failure path",
    )
    parser.add_argument(
        "--simulate-model-load-delay-s",
        type=float,
        default=0.0,
        help="Testing hook: delay model load to exercise timeout handling",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_result_path = output_dir / "run_result.json"

    base_result: dict[str, Any] = {
        "timestamp": _now_iso(),
        "status": "ok",
        "error_stage": None,
        "error_message": None,
        "dataset_root": str(Path(args.dataset_root)),
        "output_dir": str(output_dir),
        "dry_run": bool(args.dry_run),
        "model_family": "demucs",
        "track_count": 0,
        "track_artifacts": [],
        "environment": _environment_fingerprint(),
    }

    try:
        protocol = _load_protocol(Path(args.protocol))
        split = str(protocol.get("dataset", {}).get("split", "test"))
        tracks = _discover_tracks(Path(args.dataset_root), split=split, max_tracks=args.max_tracks)
        base_result["track_count"] = len(tracks)
        base_result["protocol_version"] = str(protocol.get("protocol_version", "unknown"))
        base_result["dataset"] = str(protocol.get("dataset", {}).get("name", "unknown"))

        _simulate_model_load(
            simulate_failure=bool(args.simulate_model_load_failure),
            timeout_s=float(args.model_timeout_s),
            load_delay_s=float(args.simulate_model_load_delay_s),
        )

        runtime = None
        if not args.dry_run:
            runtime = _load_demucs_runtime()

        for index, track_path in enumerate(tracks):
            if args.dry_run:
                artifact = _dry_run_track_result(track_path.name, index)
            else:
                started_at = time.perf_counter()
                artifact = _real_track_result(track_path, index, runtime)
                artifact["total_ms"] = round((time.perf_counter() - started_at) * 1000.0, 3)

            artifact_path = output_dir / f"track_{index:03d}.json"
            _write_json(artifact_path, artifact)
            base_result["track_artifacts"].append(str(artifact_path))

        _write_json(run_result_path, base_result)
    except FileNotFoundError as exc:
        base_result.update(
            {
                "status": "dataset_not_found",
                "error_stage": "dataset_access",
                "error_message": str(exc),
            }
        )
        _write_json(run_result_path, base_result)
        print(f"dataset_not_found: {exc}", file=sys.stderr)
        return 2
    except TimeoutError as exc:
        base_result.update(
            {
                "status": "error",
                "error_stage": "model_load_timeout",
                "error_message": str(exc),
            }
        )
        _write_json(run_result_path, base_result)
        print(f"model_load_timeout: {exc}", file=sys.stderr)
        return 3
    except RuntimeError as exc:
        base_result.update(
            {
                "status": "error",
                "error_stage": "model_load_failed",
                "error_message": str(exc),
            }
        )
        _write_json(run_result_path, base_result)
        print(f"model_load_failed: {exc}", file=sys.stderr)
        return 4
    except ValueError as exc:
        base_result.update(
            {
                "status": "error",
                "error_stage": "dataset_access",
                "error_message": str(exc),
            }
        )
        _write_json(run_result_path, base_result)
        print(f"dataset_access_error: {exc}", file=sys.stderr)
        return 5
    except Exception as exc:
        base_result.update(
            {
                "status": "error",
                "error_stage": "run_demucs_eval",
                "error_message": str(exc),
            }
        )
        _write_json(run_result_path, base_result)
        print(f"run_demucs_eval_error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote run artifact: {run_result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
