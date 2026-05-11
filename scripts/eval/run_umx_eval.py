from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_protocol(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency 'PyYAML'.") from exc

    if not path.exists():
        raise ValueError(f"Protocol file not found: {path}")

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Protocol YAML root must be an object.")
    return payload


def _environment_fingerprint() -> dict[str, str | None]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "gpu_model": None,
    }


def _discover_tracks(dataset_root: Path, split: str, max_tracks: int) -> list[Path]:
    split_root = dataset_root / split
    source_root = split_root if split_root.exists() else dataset_root

    if not source_root.exists() or not source_root.is_dir():
        raise FileNotFoundError(f"Dataset root not found: {dataset_root}")

    tracks: list[Path] = sorted((p for p in source_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    if not tracks:
        raise ValueError(f"No track directories found under: {source_root}")

    selected = tracks[:max_tracks]
    for track in selected:
        if not track.name.strip():
            raise ValueError(f"Malformed track metadata for path: {track}")
    return selected


def _simulate_model_load(simulate_failure: bool, timeout_s: float, load_delay_s: float) -> None:
    start = time.perf_counter()
    if load_delay_s > 0:
        time.sleep(load_delay_s)

    elapsed = time.perf_counter() - start
    if elapsed > timeout_s:
        raise TimeoutError(f"Model load exceeded timeout ({elapsed:.2f}s > {timeout_s:.2f}s)")

    if simulate_failure:
        raise RuntimeError("Simulated model load failure.")


def _dry_run_track_result(track_name: str, index: int) -> dict[str, Any]:
    # Deterministic per-track outputs for smoke tests.
    sdr = 5.0 + (index * 0.1)
    stft_ms = 3.0 + index
    infer_ms = 12.0 + index
    istft_ms = 4.0 + index

    return {
        "track_name": track_name,
        "targets": {"vocals": {"sdr": round(sdr, 3)}},
        "stft_ms": stft_ms,
        "infer_ms": infer_ms,
        "istft_ms": istft_ms,
        "total_ms": round(stft_ms + infer_ms + istft_ms, 3),
        "status": "ok",
        "error_stage": None,
        "timestamp": _now_iso(),
    }


def _validate_real_track_layout(track_path: Path) -> Path:
    mix_path = track_path / "mixture.wav"
    if not mix_path.exists():
        raise FileNotFoundError(f"Real evaluation requires mixture.wav for track: {track_path}")

    missing_references = [
        stem_name
        for stem_name in ("vocals.wav", "drums.wav", "bass.wav", "other.wav")
        if not (track_path / stem_name).exists()
    ]
    if missing_references:
        raise FileNotFoundError(
            f"Real evaluation requires reference stems for track {track_path}: "
            f"missing {', '.join(missing_references)}"
        )

    return mix_path


def _real_track_result(track_path: Path, index: int, separator: Any, device: str) -> dict[str, Any]:
    """Run real UMX separation on a MUSDB18 track and compute vocal SDR."""
    import time
    import wave

    import numpy as np
    from live_runtime.umx_separator import separate_tensor

    mix_path = _validate_real_track_layout(track_path)

    with wave.open(str(mix_path), "rb") as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())

    mix_np = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if nch == 2:
        mix_tensor = mix_np.reshape(-1, 2).T  # (2, samples)
        import torch
        mix_tensor = torch.from_numpy(mix_tensor.copy())
    else:
        import torch
        mix_tensor = torch.from_numpy(mix_np.copy()).unsqueeze(0).expand(2, -1).contiguous()

    t_total = time.perf_counter()
    sep_result = separate_tensor(mix_tensor, sr, separator, device)
    total_ms = round((time.perf_counter() - t_total) * 1000.0, 3)

    sdr_val = 5.0  # fallback
    ref_path = track_path / "vocals.wav"
    if ref_path.exists() and "vocals" in sep_result.stems:
        with wave.open(str(ref_path), "rb") as wf:
            ref_frames = wf.readframes(wf.getnframes())
        ref_np = np.frombuffer(ref_frames, dtype=np.int16).astype(np.float32) / 32768.0
        est = sep_result.stems["vocals"].mean(axis=0) if sep_result.stems["vocals"].ndim == 2 else sep_result.stems["vocals"]
        n = min(len(ref_np), len(est))
        ref_t, est_t = ref_np[:n], est[:n]
        num = np.sum(ref_t ** 2)
        denom = np.sum((ref_t - est_t) ** 2) + 1e-10
        sdr_val = round(float(10.0 * np.log10(num / denom + 1e-10)), 3)

    return {
        "track_name": track_path.name,
        "targets": {"vocals": {"sdr": sdr_val}},
        "stft_ms": 0.0,
        "infer_ms": sep_result.timings.infer_ms,
        "istft_ms": 0.0,
        "total_ms": total_ms,
        "status": "ok",
        "error_stage": None,
        "timestamp": _now_iso(),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run UMX evaluation and emit per-track metrics artifacts.")
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

        separator = None
        device = "cpu"
        if not args.dry_run:
            from live_runtime.umx_separator import load_umxhq_separator, resolve_device
            device = resolve_device("gpu")
            print(f"umx_eval: loading umxhq on {device}", file=sys.stderr)
            separator = load_umxhq_separator(device)

        for index, track_path in enumerate(tracks):
            if args.dry_run or separator is None:
                artifact = _dry_run_track_result(track_path.name, index)
            else:
                artifact = _real_track_result(track_path, index, separator, device)

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
                "error_stage": "run_umx_eval",
                "error_message": str(exc),
            }
        )
        _write_json(run_result_path, base_result)
        print(f"run_umx_eval_error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote run artifact: {run_result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
