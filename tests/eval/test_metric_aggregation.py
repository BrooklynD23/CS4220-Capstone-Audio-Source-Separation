from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.eval.aggregate_metrics import aggregate_summary, extract_vocals_sdr
FIXTURE_DIR = PROJECT_ROOT / "tests/fixtures/eval"
PROTOCOL_PATH = PROJECT_ROOT / "scripts/eval/eval_protocol.yaml"
RUNNER_PATH = PROJECT_ROOT / "scripts/eval/run_umx_eval.py"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_aggregate_is_deterministic_independent_of_ordering() -> None:
    track_results = _load_json(FIXTURE_DIR / "sample_track_metrics.json")

    forward = aggregate_summary(
        track_results=track_results,
        threshold_db=5.0,
        protocol_version="1.0",
        dataset="musdb18",
    )
    reverse = aggregate_summary(
        track_results=list(reversed(track_results)),
        threshold_db=5.0,
        protocol_version="1.0",
        dataset="musdb18",
    )

    assert forward["vocal_sdr_median_db"] == pytest.approx(5.0)
    assert reverse["vocal_sdr_median_db"] == pytest.approx(5.0)
    assert forward["passes_threshold"] is True
    assert reverse["passes_threshold"] is True


def test_exact_threshold_counts_as_pass() -> None:
    payload = _load_json(FIXTURE_DIR / "sample_summary_input.json")
    summary = aggregate_summary(
        track_results=payload["track_results"],
        threshold_db=payload["threshold_db"],
        protocol_version=payload["protocol_version"],
        dataset=payload["dataset"],
    )

    assert summary["vocal_sdr_median_db"] == pytest.approx(5.0)
    assert summary["passes_threshold"] is True


@pytest.mark.parametrize(
    "bad_payload",
    [
        [],
        [{"track_name": "x", "targets": {"drums": {"sdr": 1.0}}}],
        [{"track_name": "x", "targets": {"vocals": {"sdr": "nan"}}}],
        [{"track_name": "x", "targets": {"vocals": {"sdr": float("nan")}}}],
        [{"track_name": "x", "targets": {"vocals": {"sdr": float("inf")}}}],
    ],
)
def test_extract_vocals_sdr_rejects_malformed_inputs(bad_payload) -> None:
    with pytest.raises(ValueError):
        extract_vocals_sdr(bad_payload)


def test_single_track_payload_is_supported() -> None:
    payload = [{"track_name": "single", "targets": {"vocals": {"sdr": 4.75}}}]
    summary = aggregate_summary(
        track_results=payload,
        threshold_db=5.0,
        protocol_version="1.0",
        dataset="musdb18",
    )

    assert summary["track_count"] == 1
    assert summary["vocal_sdr_median_db"] == pytest.approx(4.75)
    assert summary["passes_threshold"] is False


def test_runner_missing_dataset_root_returns_dataset_not_found(tmp_path: Path) -> None:
    output_dir = tmp_path / "eval_output"
    cmd = [
        sys.executable,
        str(RUNNER_PATH),
        "--protocol",
        str(PROTOCOL_PATH),
        "--dataset-root",
        str(tmp_path / "does_not_exist"),
        "--output",
        str(output_dir),
        "--max-tracks",
        "1",
        "--dry-run",
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode != 0
    assert "dataset_not_found" in proc.stderr

    run_result = _load_json(output_dir / "run_result.json")
    assert run_result["status"] == "dataset_not_found"
    assert run_result["error_stage"] == "dataset_access"


def test_runner_model_load_failure_surfaces_stage_marker(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    (dataset_root / "test" / "TrackOne").mkdir(parents=True)

    output_dir = tmp_path / "eval_output"
    cmd = [
        sys.executable,
        str(RUNNER_PATH),
        "--protocol",
        str(PROTOCOL_PATH),
        "--dataset-root",
        str(dataset_root),
        "--output",
        str(output_dir),
        "--max-tracks",
        "1",
        "--dry-run",
        "--simulate-model-load-failure",
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode != 0
    assert "model_load_failed" in proc.stderr

    run_result = _load_json(output_dir / "run_result.json")
    assert run_result["status"] == "error"
    assert run_result["error_stage"] == "model_load_failed"
    assert "model" in run_result["error_message"].lower()
