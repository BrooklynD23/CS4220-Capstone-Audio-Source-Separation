from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import jsonschema
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts/benchmark/run_live_throughput.py"
THROUGHPUT_SCHEMA_PATH = PROJECT_ROOT / "artifacts/schema/live_throughput_result.schema.json"
LIVE_RUNTIME_SCHEMA_PATH = PROJECT_ROOT / "artifacts/schema/live_runtime_result.schema.json"
FIXTURE_INPUT = PROJECT_ROOT / "fixtures/audio/demo_mix.mp3"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_live_throughput", SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive guard
        raise RuntimeError(f"unable to load module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop("run_live_throughput", None)
    spec.loader.exec_module(module)
    return module


def _load_schema(path: Path) -> dict[str, Any]:
    return _load_json(path)


def _build_live_runtime_payload(
    *,
    output_dir: Path,
    input_path: Path,
    status: str = "ok",
    stem_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "source": {
            "kind": "mp3",
            "reference": str(input_path),
            "metadata": {
                "origin": "fixture",
            },
        },
        "input": str(input_path),
        "sample_rate_hz": 22050,
        "chunk_duration_s": 1.0,
        "chunk_index": 0,
        "stft_ms": 120.0,
        "infer_ms": 240.0,
        "istft_ms": 80.0,
        "total_ms": 440.0,
        "status": status,
        "error_stage": None if status == "ok" else "decode_failed",
        "error_message": None if status == "ok" else "fixture runtime failed",
        "timestamp": "2026-04-20T00:00:00+00:00",
        "health_state": "healthy",
        "health_reason": "runtime operating normally",
        "requested_model_path": "artifacts/models/live.pt",
        "fallback_applied": False,
        "queue_depth": 20,
        "drop_count": 0,
        "model_path": "artifacts/models/live.pt",
        "stem_paths": stem_paths
        if stem_paths is not None
        else {
            "vocals": str(output_dir / "vocals.wav"),
            "drums": str(output_dir / "drums.wav"),
            "bass": str(output_dir / "bass.wav"),
            "other": str(output_dir / "other.wav"),
        },
        "metadata": {
            "device_requested": "cpu",
            "device_used": "cpu",
            "mode": "smoke",
            "clock_source": "ingest",
            "clock_fallback": False,
            "samples_processed": 22050,
            "channels": 1,
            "sample_width_bytes": 2,
            "stages": ["stft", "infer", "istft"],
        },
    }


def _write_live_runtime_payload(
    path: Path,
    output_dir: Path,
    input_path: Path,
    *,
    malformed: bool = False,
    status: str = "ok",
    stem_paths: dict[str, str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if malformed:
        path.write_text("{not-json", encoding="utf-8")
        return
    path.write_text(
        json.dumps(
            _build_live_runtime_payload(
                output_dir=output_dir,
                input_path=input_path,
                status=status,
                stem_paths=stem_paths,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture()
def throughput_module() -> ModuleType:
    return _load_module()


def test_throughput_benchmark_happy_path_measures_wall_clock_and_writes_schema_valid_artifact(
    throughput_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "bench"
    artifact_path = output_dir / "live_throughput_result.json"
    live_artifact_path = output_dir / "live_runtime_result.json"
    calls: list[list[str]] = []
    clock_values = iter([10.0, 12.25])

    def fake_clock() -> float:
        return next(clock_values)

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        _write_live_runtime_payload(live_artifact_path, output_dir, FIXTURE_INPUT)
        return subprocess.CompletedProcess(command, 0, stdout="live_runtime_artifact\n", stderr="")

    monkeypatch.setattr(throughput_module.subprocess, "run", fake_run)
    monkeypatch.setattr(throughput_module.time, "perf_counter", fake_clock)

    payload, exit_code = throughput_module.run_live_throughput_benchmark(
        input_path=FIXTURE_INPUT,
        output_dir=output_dir,
        artifact_path=artifact_path,
        live_artifact_path=live_artifact_path,
        chunk_duration_s=1.0,
        max_wall_clock_ms=5000.0,
        clock=fake_clock,
    )

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0][0] == sys.executable
    assert calls[0][1] == str(throughput_module.LIVE_CLI_SCRIPT)
    assert calls[0][calls[0].index("--chunk-duration-s") + 1] == "1.0"

    schema = _load_schema(THROUGHPUT_SCHEMA_PATH)
    jsonschema.Draft202012Validator(schema).validate(payload)

    written = _load_json(artifact_path)
    assert written == payload
    assert payload["status"] == "ok"
    assert payload["phase"] == "complete"
    assert payload["error_stage"] is None
    assert payload["error_message"] is None
    assert payload["live_cli_exit_code"] == 0
    assert payload["live_runtime_status"] == "ok"
    assert payload["live_runtime_error_stage"] is None
    assert payload["live_runtime_error_message"] is None
    assert payload["wall_clock_ms"] == pytest.approx(2250.0)
    assert payload["wall_clock_ms_per_chunk"] == pytest.approx(2250.0)
    assert payload["throughput_chunks_per_second"] == pytest.approx(0.444444, rel=1e-6)
    assert payload["live_artifact_path"] == str(live_artifact_path)
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "live_runtime_result.json",
        "live_throughput_result.json",
    ]


def test_throughput_benchmark_rejects_malformed_live_artifact(
    throughput_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "bench"
    artifact_path = output_dir / "live_throughput_result.json"
    live_artifact_path = output_dir / "live_runtime_result.json"

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        _write_live_runtime_payload(live_artifact_path, output_dir, FIXTURE_INPUT, malformed=True)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="runtime wrote malformed json\n")

    clock_values = iter([1.0, 2.0])

    def fake_clock_seq() -> float:
        return next(clock_values)

    monkeypatch.setattr(throughput_module.subprocess, "run", fake_run)
    monkeypatch.setattr(throughput_module.time, "perf_counter", fake_clock_seq)

    payload, exit_code = throughput_module.run_live_throughput_benchmark(
        input_path=FIXTURE_INPUT,
        output_dir=output_dir,
        artifact_path=artifact_path,
        live_artifact_path=live_artifact_path,
        clock=fake_clock_seq,
    )

    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["phase"] == "malformed_runtime_artifact"
    assert payload["error_stage"] == "malformed_runtime_artifact"
    assert "valid JSON" in payload["error_message"]
    assert payload["stderr"] == "runtime wrote malformed json\n"
    assert payload["live_cli_exit_code"] == 0
    assert payload["live_runtime_status"] is None
    assert _load_json(artifact_path) == payload


def test_throughput_benchmark_rejects_missing_live_artifact_output(
    throughput_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "bench"
    artifact_path = output_dir / "live_throughput_result.json"
    live_artifact_path = output_dir / "live_runtime_result.json"
    clock_values = iter([2.0, 3.5])

    def fake_clock() -> float:
        return next(clock_values)

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(throughput_module.subprocess, "run", fake_run)
    monkeypatch.setattr(throughput_module.time, "perf_counter", fake_clock)

    payload, exit_code = throughput_module.run_live_throughput_benchmark(
        input_path=FIXTURE_INPUT,
        output_dir=output_dir,
        artifact_path=artifact_path,
        live_artifact_path=live_artifact_path,
        clock=fake_clock,
    )

    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["phase"] == "missing_runtime_artifact"
    assert payload["error_stage"] == "missing_runtime_artifact"
    assert str(live_artifact_path) in payload["error_message"]
    assert payload["stderr"] == ""
    assert payload["live_cli_exit_code"] == 0
    assert _load_json(artifact_path) == payload


def test_throughput_benchmark_preserves_failure_phase_for_nonzero_live_cli_exit(
    throughput_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "bench"
    artifact_path = output_dir / "live_throughput_result.json"
    live_artifact_path = output_dir / "live_runtime_result.json"
    clock_values = iter([5.0, 6.2])

    def fake_clock() -> float:
        return next(clock_values)

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 7, stdout="", stderr="live runtime crashed\n")

    monkeypatch.setattr(throughput_module.subprocess, "run", fake_run)
    monkeypatch.setattr(throughput_module.time, "perf_counter", fake_clock)

    payload, exit_code = throughput_module.run_live_throughput_benchmark(
        input_path=FIXTURE_INPUT,
        output_dir=output_dir,
        artifact_path=artifact_path,
        live_artifact_path=live_artifact_path,
        clock=fake_clock,
    )

    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["phase"] == "live_cli_failed"
    assert payload["error_stage"] == "live_cli_failed"
    assert payload["live_cli_exit_code"] == 7
    assert payload["live_artifact_path"] == str(live_artifact_path)
    assert payload["stderr"] == "live runtime crashed\n"
    assert payload["error_message"] == "live CLI exited 7"
    assert _load_json(artifact_path) == payload


def test_throughput_benchmark_marks_over_budget_runs_as_failure(
    throughput_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "bench"
    artifact_path = output_dir / "live_throughput_result.json"
    live_artifact_path = output_dir / "live_runtime_result.json"
    clock_values = iter([11.0, 14.4])

    def fake_clock() -> float:
        return next(clock_values)

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        _write_live_runtime_payload(live_artifact_path, output_dir, FIXTURE_INPUT)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(throughput_module.subprocess, "run", fake_run)
    monkeypatch.setattr(throughput_module.time, "perf_counter", fake_clock)

    payload, exit_code = throughput_module.run_live_throughput_benchmark(
        input_path=FIXTURE_INPUT,
        output_dir=output_dir,
        artifact_path=artifact_path,
        live_artifact_path=live_artifact_path,
        max_wall_clock_ms=2000.0,
        clock=fake_clock,
    )

    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["phase"] == "throughput_budget_exceeded"
    assert payload["error_stage"] == "throughput_budget_exceeded"
    assert "2000.000ms" in payload["error_message"]
    assert payload["live_cli_exit_code"] == 0
    assert payload["live_runtime_status"] == "ok"
    assert payload["wall_clock_ms"] == pytest.approx(3400.0)
    assert payload["wall_clock_ms_per_chunk"] == pytest.approx(3400.0)
    assert payload["throughput_chunks_per_second"] == pytest.approx(0.294118, rel=1e-6)
    assert _load_json(artifact_path) == payload


@pytest.mark.parametrize(
    ("stem_paths", "expected_fragment"),
    [
        ({"vocals": "a.wav", "drums": "b.wav", "bass": "c.wav"}, "'other' is a required property"),
        ({"vocals": "a.wav", "bass": "c.wav", "other": "d.wav"}, "'drums' is a required property"),
        ({"vocals": "a.wav", "drums": "b.wav", "other": "d.wav"}, "'bass' is a required property"),
        ({}, "'vocals' is a required property"),
        (
            {
                "vocals": "a.wav",
                "drums": "b.wav",
                "bass": "c.wav",
                "other": "d.wav",
                "instrumental": "e.wav",
            },
            "Additional properties are not allowed",
        ),
    ],
)
def test_throughput_benchmark_rejects_invalid_live_runtime_stem_shapes(
    throughput_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stem_paths: dict[str, str],
    expected_fragment: str,
) -> None:
    output_dir = tmp_path / "bench"
    artifact_path = output_dir / "live_throughput_result.json"
    live_artifact_path = output_dir / "live_runtime_result.json"

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        _write_live_runtime_payload(
            live_artifact_path,
            output_dir,
            FIXTURE_INPUT,
            stem_paths=stem_paths,
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="runtime wrote widened json\n")

    clock_values = iter([1.0, 2.0])

    def fake_clock_seq() -> float:
        return next(clock_values)

    monkeypatch.setattr(throughput_module.subprocess, "run", fake_run)
    monkeypatch.setattr(throughput_module.time, "perf_counter", fake_clock_seq)

    payload, exit_code = throughput_module.run_live_throughput_benchmark(
        input_path=FIXTURE_INPUT,
        output_dir=output_dir,
        artifact_path=artifact_path,
        live_artifact_path=live_artifact_path,
        clock=fake_clock_seq,
    )

    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["phase"] == "invalid_runtime_payload"
    assert payload["error_stage"] == "invalid_runtime_payload"
    assert expected_fragment in payload["error_message"]
    assert payload["stderr"] == "runtime wrote widened json\n"
    assert payload["live_cli_exit_code"] == 0
    assert payload["live_runtime_status"] is None
    assert _load_json(artifact_path) == payload


@pytest.mark.parametrize("chunk_duration_s", [0.0, -1.0])
def test_throughput_benchmark_rejects_non_positive_chunk_duration(
    throughput_module: ModuleType,
    tmp_path: Path,
    chunk_duration_s: float,
) -> None:
    with pytest.raises(ValueError, match="chunk_duration_s must be positive"):
        throughput_module.run_live_throughput_benchmark(
            input_path=FIXTURE_INPUT,
            output_dir=tmp_path / "bench",
            chunk_duration_s=chunk_duration_s,
        )
