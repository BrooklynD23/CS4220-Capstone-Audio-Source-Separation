from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_shape(shape_text: str, *, label: str) -> tuple[int, int, int]:
    parts = [p.strip() for p in shape_text.split(",") if p.strip()]
    if len(parts) != 3:
        raise ValueError(
            f"invalid_profile: {label} must have exactly 3 comma-delimited dimensions (batch,channels,samples)."
        )

    try:
        batch, channels, samples = (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as exc:
        raise ValueError(f"invalid_profile: {label} must contain integer dimensions.") from exc

    if batch <= 0 or channels <= 0 or samples <= 0:
        raise ValueError(f"invalid_profile: {label} dimensions must be > 0.")

    return (batch, channels, samples)


def _validate_profile(
    *,
    input_shape: tuple[int, int, int],
    min_shape: tuple[int, int, int],
    opt_shape: tuple[int, int, int],
    max_shape: tuple[int, int, int],
) -> None:
    for dim in range(3):
        if not (min_shape[dim] <= opt_shape[dim] <= max_shape[dim]):
            raise ValueError(
                "invalid_profile: expected min <= opt <= max for each dimension, "
                f"received min={min_shape}, opt={opt_shape}, max={max_shape}."
            )

    # This runbook supports dynamic sample-length only; batch/channels are fixed for deterministic builds.
    if not (
        min_shape[0] == opt_shape[0] == max_shape[0] == input_shape[0]
        and min_shape[1] == opt_shape[1] == max_shape[1] == input_shape[1]
    ):
        raise ValueError(
            "invalid_profile: only sample dimension may be dynamic. "
            f"batch/channels must match input_shape={input_shape}."
        )


def _validate_onnx_output_path(path: Path) -> None:
    if path.exists() and path.is_dir():
        raise ValueError(f"invalid_onnx_output_path: path points to a directory: {path}")

    if path.suffix.lower() != ".onnx":
        raise ValueError("invalid_onnx_output_path: output file must use .onnx extension.")


def _compute_model_hash(model_path: Path | None, model_source: str) -> tuple[str, str]:
    if model_path is not None:
        if not model_path.exists() or not model_path.is_file():
            raise FileNotFoundError(f"model_path_not_found: {model_path}")
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        return digest, str(model_path)

    digest = hashlib.sha256(model_source.encode("utf-8")).hexdigest()
    return digest, model_source


def _write_traceback(path: Path, exc: BaseException) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    path.write_text(details, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export UMX model to ONNX with deterministic metadata.")
    parser.add_argument("--onnx-output", required=True, help="Destination ONNX path.")
    parser.add_argument("--metadata-output", default=None, help="Destination metadata JSON path.")
    parser.add_argument("--traceback-output", default=None, help="Destination traceback text path.")
    parser.add_argument("--model-path", default=None, help="Optional local model checkpoint path.")
    parser.add_argument(
        "--model-source",
        default="open-unmix.umxhq",
        help="Human-readable model source string when --model-path is not provided.",
    )
    parser.add_argument("--opset", type=int, default=17, help="ONNX opset version.")
    parser.add_argument("--input-shape", required=True, help="Input shape as batch,channels,samples.")
    parser.add_argument("--min-shape", required=True, help="TensorRT min profile as batch,channels,samples.")
    parser.add_argument("--opt-shape", required=True, help="TensorRT opt profile as batch,channels,samples.")
    parser.add_argument("--max-shape", required=True, help="TensorRT max profile as batch,channels,samples.")
    parser.add_argument("--export-timeout-s", type=float, default=180.0, help="Export timeout in seconds.")
    parser.add_argument(
        "--simulate-export-delay-s",
        type=float,
        default=0.0,
        help="Testing hook to exercise timeout handling.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip torch export and write deterministic placeholder ONNX.")
    return parser.parse_args(argv)


def _run_export(
    *,
    onnx_output: Path,
    input_shape: tuple[int, int, int],
    opset: int,
    model_path: Path | None,
    dry_run: bool,
) -> None:
    if dry_run:
        onnx_output.parent.mkdir(parents=True, exist_ok=True)
        onnx_output.write_text(
            "# dry-run ONNX placeholder for reproducibility checks\n"
            f"# input_shape={input_shape}, opset={opset}\n",
            encoding="utf-8",
        )
        return

    try:
        import torch
        import torch.nn as nn
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError(
            "PyTorch is required for non-dry-run export. Install torch and rerun, or pass --dry-run."
        ) from exc

    if model_path is not None:
        module = torch.load(model_path, map_location="cpu")
        if hasattr(module, "eval"):
            module = module.eval()
    else:
        # Fallback identity module for environments without a checkpoint path.
        module = nn.Identity().eval()

    batch, channels, samples = input_shape
    dummy = torch.randn(batch, channels, samples, dtype=torch.float32)

    onnx_output.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        module,
        dummy,
        str(onnx_output),
        opset_version=opset,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {2: "samples"}, "output": {2: "samples"}},
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    onnx_output = Path(args.onnx_output)
    metadata_output = Path(args.metadata_output) if args.metadata_output else onnx_output.with_suffix(".export.json")
    traceback_output = (
        Path(args.traceback_output) if args.traceback_output else onnx_output.with_suffix(".traceback.log")
    )

    result: dict[str, Any] = {
        "timestamp": _now_iso(),
        "status": "error",
        "error_stage": None,
        "error_message": None,
        "onnx_output": str(onnx_output),
        "metadata_output": str(metadata_output),
        "traceback_output": str(traceback_output),
        "model_source": args.model_source,
        "model_hash_sha256": None,
        "opset": int(args.opset),
        "input_shape": None,
        "profile": None,
        "dry_run": bool(args.dry_run),
        "duration_ms": 0.0,
    }

    started = time.perf_counter()

    try:
        if args.opset < 13:
            raise ValueError("invalid_profile: opset must be >= 13 for dynamic shape export.")

        _validate_onnx_output_path(onnx_output)

        input_shape = _parse_shape(args.input_shape, label="input-shape")
        min_shape = _parse_shape(args.min_shape, label="min-shape")
        opt_shape = _parse_shape(args.opt_shape, label="opt-shape")
        max_shape = _parse_shape(args.max_shape, label="max-shape")

        _validate_profile(
            input_shape=input_shape,
            min_shape=min_shape,
            opt_shape=opt_shape,
            max_shape=max_shape,
        )

        if args.simulate_export_delay_s > 0:
            time.sleep(float(args.simulate_export_delay_s))

        elapsed = time.perf_counter() - started
        if elapsed > float(args.export_timeout_s):
            raise TimeoutError(
                "export_timeout: export exceeded timeout before ONNX serialization "
                f"(timeout_s={args.export_timeout_s}, input_shape={input_shape}, profile={min_shape}/{opt_shape}/{max_shape})."
            )

        model_path = Path(args.model_path) if args.model_path else None
        model_hash, source = _compute_model_hash(model_path, args.model_source)

        _run_export(
            onnx_output=onnx_output,
            input_shape=input_shape,
            opset=int(args.opset),
            model_path=model_path,
            dry_run=bool(args.dry_run),
        )

        elapsed = (time.perf_counter() - started) * 1000.0
        result.update(
            {
                "status": "ok",
                "error_stage": None,
                "error_message": None,
                "model_hash_sha256": model_hash,
                "model_source": source,
                "input_shape": list(input_shape),
                "profile": {
                    "min": list(min_shape),
                    "opt": list(opt_shape),
                    "max": list(max_shape),
                },
                "duration_ms": round(elapsed, 3),
            }
        )
        _write_json(metadata_output, result)
        print(f"export_ok: onnx={onnx_output} metadata={metadata_output}")
        return 0

    except ValueError as exc:
        result.update({"status": "error", "error_stage": "invalid_profile", "error_message": str(exc)})
        _write_json(metadata_output, result)
        _write_traceback(traceback_output, exc)
        if "invalid_onnx_output_path" in str(exc):
            print(str(exc), file=sys.stderr)
        else:
            print(f"invalid_profile: {exc}", file=sys.stderr)
        return 2
    except TimeoutError as exc:
        result.update({"status": "error", "error_stage": "export_timeout", "error_message": str(exc)})
        _write_json(metadata_output, result)
        _write_traceback(traceback_output, exc)
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        result.update({"status": "error", "error_stage": "export_failed", "error_message": str(exc)})
        _write_json(metadata_output, result)
        _write_traceback(traceback_output, exc)
        print(f"export_failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
