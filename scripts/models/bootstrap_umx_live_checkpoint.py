"""Download Open-Unmix umxhq pretrained weights and save under artifacts/models/.

The live launcher only checks that ``artifacts/models/umx-live.pt`` exists; full
mode inference loads umxhq via ``openunmix.umxhq(..., pretrained=True)``. This
script materializes a non-empty checkpoint at the runbook path so tooling,
hashes, and ops layouts stay consistent. The saved file is a dict with
``state_dict`` (``nn.Module.state_dict`` from the frozen Separator) plus
metadata; it is not loaded by the current full-mode path unless you wire it in.

Requires: ``pip install -e ".[gpu]"`` (or torch + openunmix on PYTHONPATH).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Destination .pt path (default: <repo>/artifacts/models/umx-live.pt)",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Torch device for load (cpu avoids CUDA requirement for bootstrap).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = args.output
    if out is None:
        out = _repo_root() / "artifacts" / "models" / "umx-live.pt"

    try:
        import torch
    except ModuleNotFoundError as exc:
        print("PyTorch is required. Install with: pip install -e \".[gpu]\"", file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        from live_runtime.umx_separator import STEM_NAMES, load_umxhq_separator
    except ImportError as exc:
        print("Run from repo root with the package installed: pip install -e .", file=sys.stderr)
        raise SystemExit(1) from exc

    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"Loading umxhq (pretrained, device={args.device})...", flush=True)
    separator = load_umxhq_separator(device=args.device)
    if not hasattr(separator, "state_dict"):
        print("separator has no state_dict; saving module via __dict__ is unsupported.", file=sys.stderr)
        raise SystemExit(2)

    payload = {
        "format": "openunmix.umxhq.state_dict.v1",
        "targets": list(STEM_NAMES),
        "sample_rate": getattr(separator, "sample_rate", None),
        "state_dict": separator.state_dict(),
    }
    torch.save(payload, out)
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"Wrote {out} ({size_mb:.2f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
