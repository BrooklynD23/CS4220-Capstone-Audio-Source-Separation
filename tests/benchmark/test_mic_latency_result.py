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
SCRIPT_PATH = PROJECT_ROOT / "scripts/benchmark/run_mic_latency.py"
MIC_LATENCY_SCHEMA_PATH = PROJECT_ROOT / "artifacts/schema/mic_latency_result.schema.json"
LIVE_RUNTIME_SCHEMA_PATH = PROJECT_ROOT / "artifacts/schema/live_runtime_result.schema.json"
FIXTURE_INPUT = PROJECT_ROOT / "fixtures/audio/demo_mix.mp3"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_mic_latency", SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive guard
        raise RuntimeError(f"unable to load module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop("run_mic_latency", None)
    spec.loader.exec_module(module)
    return module


def _load_schema(path: Path) -> dict[str, Any]:
    return _load_json(path)


def _build_live_runtime_payload(
    *,
    output_dir: Path,
    input_path: str,
    status: str = "ok",
    backend_name: str = "fake",
    stft_ms: float = 123.456,
    stem_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "source": {
            "kind": "mic",
            "reference": input_path,
            "metadata": {
                "backend": backend_name,
                "device": input_path,
                "capture_duration_s": 1.0,
                "sample_rate_hz": 22050,
            },
        },
        "input": input_path,
        "sample_rate_hz": 22050,
        "chunk_duration_s": 1.0,
        "chunk_index": 0,
        "stft_ms": stft_ms,
        "infer_ms": 15.0,
        "istft_ms": 5.0,
        "total_ms": stft_ms + 20.0,
        "status": status,
        "error_stage": None if status == "ok" else "capture_failed",
        "error_message": None if status == "ok" else "fixture mic runtime failed",
        "timestamp": "2026-04-20T00:00:00+00:00",
        "health_state": "healthy",
        "health_reason": "runtime operating normally",
        "requested_model_path": "artifacts/models/umx-live.pt",
        "fallback_applied": False,
        "queue_depth": 20,
        "drop_count": 0,
        "model_path": "artifacts/models/umx-live.pt",
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
    *,
    output_dir: Path,
    input_path: str,
    malformed: bool = False,
    status: str = "ok",
    backend_name: str = "fake",
    stft_ms: float = 123.456,
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
                backend_name=backend_name,
                stft_ms=stft_ms,
                stem_paths=stem_paths,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture()
def mic_latency_module() -> ModuleType:
    return _load_module()


def test_mic_latency_benchmark_happy_path_uses_fake_backend_and_writes_schema_valid_artifact(
    mic_latency_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "bench"
    artifact_path = output_dir / "mic_latency_result.json"
    live_artifact_path = output_dir / "live_runtime_result.json"
    calls: list[list[str]] = []
    clock_values = iter([10.0, 11.25])

    def fake_clock() -> float:
        return next(clock_values)

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        _write_live_runtime_payload(
            live_artifact_path,
            output_dir=output_dir,
            input_path="fixture:mic-demo",
            backend_name="fake",
            stft_ms=321.654,
        )
        return subprocess.CompletedProcess(command, 0, stdout="live_runtime_artifact\n", stderr="")

    monkeypatch.setattr(mic_latency_module.subprocess, "run", fake_run)
    monkeypatch.setattr(mic_latency_module.time, "perf_counter", fake_clock)

    payload, exit_code = mic_latency_module.run_mic_latency_benchmark(
        output_dir=output_dir,
        artifact_path=artifact_path,
        live_artifact_path=live_artifact_path,
        capture_backend_name="fake",
        mic_device="fixture:mic-demo",
        capture_duration_s=1.0,
        clock=fake_clock,
    )

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0][0] == sys.executable
    assert calls[0][1] == str(mic_latency_module.LIVE_CLI_SCRIPT)
    assert calls[0][calls[0].index("--mic-backend") + 1] == "fake"
    assert calls[0][calls[0].index("--mic-device") + 1] == "fixture:mic-demo"

    schema = _load_schema(MIC_LATENCY_SCHEMA_PATH)
    jsonschema.Draft202012Validator(schema).validate(payload)

    written = _load_json(artifact_path)
    assert written == payload
    assert payload["status"] == "ok"
    assert payload["phase"] == "complete"
    assert payload["capture_backend_name"] == "fake"
    assert payload["capture_duration_s"] == 1.0
    assert payload["capture_latency_ms"] == pytest.approx(321.654)
    assert payload["end_to_end_latency_ms"] == pytest.approx(1250.0)
    assert payload["live_cli_exit_code"] == 0
    assert payload["live_runtime_status"] == "ok"
    assert payload["live_runtime_error_stage"] is None
    assert payload["live_runtime_error_message"] is None
    assert payload["live_artifact_path"] == str(live_artifact_path)
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "live_runtime_result.json",
        "mic_latency_result.json",
    ]


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
def test_mic_latency_benchmark_rejects_invalid_live_runtime_stem_shapes(
    mic_latency_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stem_paths: dict[str, str],
    expected_fragment: str,
) -> None:
    output_dir = tmp_path / "bench"
    artifact_path = output_dir / "mic_latency_result.json"
    live_artifact_path = output_dir / "live_runtime_result.json"

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        _write_live_runtime_payload(
            live_artifact_path,
            output_dir=output_dir,
            input_path="fixture:mic-demo",
            stem_paths=stem_paths,
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="runtime wrote widened json\n")

    clock_values = iter([1.0, 2.0])

    def fake_clock_seq() -> float:
        return next(clock_values)

    monkeypatch.setattr(mic_latency_module.subprocess, "run", fake_run)
    monkeypatch.setattr(mic_latency_module.time, "perf_counter", fake_clock_seq)

    payload, exit_code = mic_latency_module.run_mic_latency_benchmark(
        output_dir=output_dir,
        artifact_path=artifact_path,
        live_artifact_path=live_artifact_path,
        mic_device="fixture:mic-demo",
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


def test_mic_latency_benchmark_rejects_malformed_live_artifact(
    mic_latency_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "bench"
    artifact_path = output_dir / "mic_latency_result.json"
    live_artifact_path = output_dir / "live_runtime_result.json"

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        _write_live_runtime_payload(
            live_artifact_path,
            output_dir=output_dir,
            input_path="fixture:mic-demo",
            malformed=True,
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="runtime wrote malformed json\n")

    clock_values = iter([1.0, 2.0])

    def fake_clock_seq() -> float:
        return next(clock_values)

    monkeypatch.setattr(mic_latency_module.subprocess, "run", fake_run)
    monkeypatch.setattr(mic_latency_module.time, "perf_counter", fake_clock_seq)

    payload, exit_code = mic_latency_module.run_mic_latency_benchmark(
        output_dir=output_dir,
        artifact_path=artifact_path,
        live_artifact_path=live_artifact_path,
        mic_device="fixture:mic-demo",
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


def test_mic_latency_benchmark_rejects_missing_live_artifact_output(
    mic_latency_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "bench"
    artifact_path = output_dir / "mic_latency_result.json"
    live_artifact_path = output_dir / "live_runtime_result.json"
    clock_values = iter([2.0, 3.5])

    def fake_clock() -> float:
        return next(clock_values)

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(mic_latency_module.subprocess, "run", fake_run)
    monkeypatch.setattr(mic_latency_module.time, "perf_counter", fake_clock)

    payload, exit_code = mic_latency_module.run_mic_latency_benchmark(
        output_dir=output_dir,
        artifact_path=artifact_path,
        live_artifact_path=live_artifact_path,
        mic_device="fixture:mic-demo",
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


def test_mic_latency_benchmark_marks_nonzero_live_cli_exit_as_failure(
    mic_latency_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "bench"
    artifact_path = output_dir / "mic_latency_result.json"
    live_artifact_path = output_dir / "live_runtime_result.json"
    clock_values = iter([5.0, 6.2])

    def fake_clock() -> float:
        return next(clock_values)

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 7, stdout="", stderr="live runtime crashed\n")

    monkeypatch.setattr(mic_latency_module.subprocess, "run", fake_run)
    monkeypatch.setattr(mic_latency_module.time, "perf_counter", fake_clock)

    payload, exit_code = mic_latency_module.run_mic_latency_benchmark(
        output_dir=output_dir,
        artifact_path=artifact_path,
        live_artifact_path=live_artifact_path,
        mic_device="fixture:mic-demo",
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


def test_mic_latency_benchmark_marks_runtime_failure_from_live_artifact(
    mic_latency_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "bench"
    artifact_path = output_dir / "mic_latency_result.json"
    live_artifact_path = output_dir / "live_runtime_result.json"
    clock_values = iter([7.0, 7.75])

    def fake_clock() -> float:
        return next(clock_values)

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        _write_live_runtime_payload(
            live_artifact_path,
            output_dir=output_dir,
            input_path="fixture:mic-demo",
            status="error",
            backend_name="fake",
        )
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="capture timed out\n")

    monkeypatch.setattr(mic_latency_module.subprocess, "run", fake_run)
    monkeypatch.setattr(mic_latency_module.time, "perf_counter", fake_clock)

    payload, exit_code = mic_latency_module.run_mic_latency_benchmark(
        output_dir=output_dir,
        artifact_path=artifact_path,
        live_artifact_path=live_artifact_path,
        capture_backend_name="fake",
        mic_device="fixture:mic-demo",
        clock=fake_clock,
    )

    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["phase"] == "live_runtime_failed"
    assert payload["error_stage"] == "live_runtime_failed"
    assert payload["live_cli_exit_code"] == 1
    assert payload["live_runtime_status"] == "error"
    assert payload["live_runtime_error_stage"] == "capture_failed"
    assert "capture_failed" in payload["error_message"]
    assert _load_json(artifact_path) == payload


@pytest.mark.parametrize("capture_duration_s", [0.0, -1.0])
def test_mic_latency_benchmark_rejects_non_positive_capture_duration(
    mic_latency_module: ModuleType,
    tmp_path: Path,
    capture_duration_s: float,
) -> None:
    with pytest.raises(ValueError, match="capture_duration_s must be positive"):
        mic_latency_module.run_mic_latency_benchmark(
            output_dir=tmp_path / "bench",
            mic_device="fixture:mic-demo",
            capture_duration_s=capture_duration_s,
        )


def test_mic_latency_benchmark_rejects_empty_device_label(
    mic_latency_module: ModuleType,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="mic_device must be non-empty"):
        mic_latency_module.run_mic_latency_benchmark(
            output_dir=tmp_path / "bench",
            mic_device="   ",
        )
