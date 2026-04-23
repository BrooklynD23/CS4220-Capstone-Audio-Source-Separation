from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def extract_vocals_sdr(track_results: list[dict[str, Any]]) -> list[float]:
    if not track_results:
        raise ValueError("No track metrics were provided.")

    vocals_sdr: list[float] = []
    for index, track in enumerate(track_results):
        if not isinstance(track, dict):
            raise ValueError(f"Track result at index {index} must be an object.")

        targets = track.get("targets")
        if not isinstance(targets, dict) or "vocals" not in targets:
            track_name = track.get("track_name", f"index {index}")
            raise ValueError(f"Missing vocals target in track '{track_name}'.")

        vocals = targets["vocals"]
        if not isinstance(vocals, dict) or "sdr" not in vocals:
            track_name = track.get("track_name", f"index {index}")
            raise ValueError(f"Missing vocals.sdr in track '{track_name}'.")

        sdr_value = vocals["sdr"]
        if not isinstance(sdr_value, (int, float)):
            track_name = track.get("track_name", f"index {index}")
            raise ValueError(f"vocals.sdr must be numeric in track '{track_name}'.")

        sdr_float = float(sdr_value)
        if math.isnan(sdr_float) or math.isinf(sdr_float):
            track_name = track.get("track_name", f"index {index}")
            raise ValueError(f"vocals.sdr must be finite in track '{track_name}'.")

        vocals_sdr.append(sdr_float)

    return vocals_sdr


def aggregate_summary(
    *,
    track_results: list[dict[str, Any]],
    threshold_db: float,
    protocol_version: str,
    dataset: str,
) -> dict[str, Any]:
    vocals_sdr = extract_vocals_sdr(track_results)
    median = statistics.median(vocals_sdr)
    passes_threshold = median >= float(threshold_db)

    return {
        "protocol_version": protocol_version,
        "dataset": dataset,
        "track_count": len(vocals_sdr),
        "vocal_sdr_median_db": median,
        "threshold_db": float(threshold_db),
        "passes_threshold": passes_threshold,
        "pass": passes_threshold,
        "status": "ok",
        "error_stage": None,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_track_results(input_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not input_path.exists():
        raise ValueError(f"Input path not found: {input_path}")

    if input_path.is_file():
        payload = _load_json(input_path)
        if isinstance(payload, list):
            return payload, {}
        if isinstance(payload, dict) and isinstance(payload.get("track_results"), list):
            metadata = {
                "protocol_version": payload.get("protocol_version"),
                "dataset": payload.get("dataset"),
                "threshold_db": payload.get("threshold_db"),
            }
            return payload["track_results"], metadata
        raise ValueError("Input JSON must be a track-results list or object with 'track_results'.")

    run_result_path = input_path / "run_result.json"
    if run_result_path.exists():
        run_result = _load_json(run_result_path)
        if run_result.get("status") != "ok":
            raise ValueError(
                "Evaluation run did not complete successfully "
                f"(status={run_result.get('status')}, error_stage={run_result.get('error_stage')})."
            )

    track_files = sorted(input_path.glob("track_*.json"), key=lambda p: p.name)
    if not track_files:
        raise ValueError(f"No track_*.json files found in: {input_path}")

    results: list[dict[str, Any]] = []
    for track_file in track_files:
        try:
            payload = _load_json(track_file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse track metrics file: {track_file}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Track metrics file must contain an object: {track_file}")
        results.append(payload)

    return results, {}


def _load_protocol_threshold(protocol_path: Path) -> tuple[str, str, float]:
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency 'PyYAML'.") from exc

    payload = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Protocol file must contain an object.")

    protocol_version = str(payload.get("protocol_version", "unknown"))
    dataset = str(payload.get("dataset", {}).get("name", "unknown"))
    threshold_db = float(payload.get("aggregation", {}).get("threshold_db", 5.0))
    return protocol_version, dataset, threshold_db


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate UMX vocals SDR metrics into a summary verdict.")
    parser.add_argument("--input", required=True, help="Input metrics file or directory containing track_*.json")
    parser.add_argument("--output", required=True, help="Output summary JSON path")
    parser.add_argument(
        "--protocol",
        default="scripts/eval/eval_protocol.yaml",
        help="Protocol YAML path for default threshold + metadata",
    )
    parser.add_argument("--threshold-db", type=float, default=None, help="Optional threshold override")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    input_path = Path(args.input)
    output_path = Path(args.output)
    protocol_path = Path(args.protocol)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        protocol_version, dataset, protocol_threshold = _load_protocol_threshold(protocol_path)
        track_results, inline_metadata = load_track_results(input_path)

        threshold = args.threshold_db
        if threshold is None:
            threshold = inline_metadata.get("threshold_db")
        if threshold is None:
            threshold = protocol_threshold

        protocol_version = str(inline_metadata.get("protocol_version") or protocol_version)
        dataset = str(inline_metadata.get("dataset") or dataset)

        summary = aggregate_summary(
            track_results=track_results,
            threshold_db=float(threshold),
            protocol_version=protocol_version,
            dataset=dataset,
        )
        output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as exc:
        failure_payload = {
            "status": "error",
            "error_stage": "aggregate_metrics",
            "error_message": str(exc),
            "generated_at": datetime.now(UTC).isoformat(),
        }
        output_path.write_text(json.dumps(failure_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Wrote summary: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
