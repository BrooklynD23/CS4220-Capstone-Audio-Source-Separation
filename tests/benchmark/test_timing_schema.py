from __future__ import annotations

import json
import subprocess
import sys
import wave
from pathlib import Path

import jsonschema

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TIMING_SCRIPT = PROJECT_ROOT / "scripts/benchmark/run_stage_timing.py"
VALIDATOR_SCRIPT = PROJECT_ROOT / "scripts/verify/validate_json.py"
TIMING_SCHEMA = PROJECT_ROOT / "artifacts/schema/timing_result.schema.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_wav(path: Path, *, sample_rate: int, frames: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frames)


def _run_timing(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(TIMING_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _run_validator(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(VALIDATOR_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def test_benchmark_smoke_artifact_validates_against_schema(tmp_path: Path) -> None:
    output_path = tmp_path / "timing-smoke.json"

    proc = _run_timing(
        "--input",
        "fixtures/audio/10s_mix.wav",
        "--output",
        str(output_path),
        "--device",
        "cpu",
        "--smoke-mode",
    )

    assert proc.returncode == 0, proc.stderr
    payload = _load_json(output_path)

    schema = _load_json(TIMING_SCHEMA)
    jsonschema.Draft202012Validator(schema).validate(payload)

    assert payload["status"] == "ok"
    assert payload["error_stage"] is None
    assert payload["metadata"]["device_requested"] == "cpu"
    assert payload["metadata"]["mode"] == "smoke"


def test_benchmark_device_flag_does_not_change_output_shape(tmp_path: Path) -> None:
    cpu_output = tmp_path / "cpu.json"
    gpu_output = tmp_path / "gpu.json"

    cpu_proc = _run_timing(
        "--input",
        "fixtures/audio/10s_mix.wav",
        "--output",
        str(cpu_output),
        "--device",
        "cpu",
        "--smoke-mode",
    )
    gpu_proc = _run_timing(
        "--input",
        "fixtures/audio/10s_mix.wav",
        "--output",
        str(gpu_output),
        "--device",
        "gpu",
        "--smoke-mode",
    )

    assert cpu_proc.returncode == 0, cpu_proc.stderr
    assert gpu_proc.returncode == 0, gpu_proc.stderr

    cpu_payload = _load_json(cpu_output)
    gpu_payload = _load_json(gpu_output)

    assert set(cpu_payload.keys()) == set(gpu_payload.keys())


def test_benchmark_nonexistent_audio_marks_preprocess_failed(tmp_path: Path) -> None:
    output_path = tmp_path / "missing.json"

    proc = _run_timing(
        "--input",
        str(tmp_path / "does_not_exist.wav"),
        "--output",
        str(output_path),
    )

    assert proc.returncode != 0
    payload = _load_json(output_path)
    assert payload["status"] == "error"
    assert payload["error_stage"] == "preprocess_failed"


def test_benchmark_zero_length_waveform_rejected(tmp_path: Path) -> None:
    wav_path = tmp_path / "zero.wav"
    output_path = tmp_path / "zero.json"
    _write_wav(wav_path, sample_rate=44100, frames=0)

    proc = _run_timing("--input", str(wav_path), "--output", str(output_path))

    assert proc.returncode != 0
    payload = _load_json(output_path)
    assert payload["error_stage"] == "preprocess_failed"
    assert "zero-length" in (payload["error_message"] or "").lower()


def test_benchmark_invalid_stage_config_fails(tmp_path: Path) -> None:
    output_path = tmp_path / "invalid-stage.json"

    proc = _run_timing(
        "--input",
        "fixtures/audio/10s_mix.wav",
        "--output",
        str(output_path),
        "--stages",
        "stft,bad,istft",
    )

    assert proc.returncode != 0
    payload = _load_json(output_path)
    assert payload["error_stage"] == "stage_config"


def test_benchmark_minimal_one_frame_audio(tmp_path: Path) -> None:
    wav_path = tmp_path / "one-frame.wav"
    output_path = tmp_path / "one-frame.json"
    _write_wav(wav_path, sample_rate=8000, frames=1)

    proc = _run_timing("--input", str(wav_path), "--output", str(output_path), "--device", "cpu")

    assert proc.returncode == 0, proc.stderr
    payload = _load_json(output_path)
    assert payload["sample_rate_hz"] == 8000
    assert payload["chunk_duration_s"] > 0


def test_validator_reports_pointer_on_schema_mismatch(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.json"
    payload_path = tmp_path / "payload.json"

    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {"count": {"type": "integer", "minimum": 1}},
                "required": ["count"],
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    payload_path.write_text(json.dumps({"count": 0}), encoding="utf-8")

    proc = _run_validator("--schema", str(schema_path), "--input", str(payload_path))

    assert proc.returncode != 0
    assert "/count" in proc.stderr


def test_validator_bad_schema_path_fails_closed(tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps({"x": 1}), encoding="utf-8")

    proc = _run_validator(
        "--schema",
        str(tmp_path / "missing-schema.json"),
        "--input",
        str(payload_path),
    )

    assert proc.returncode != 0
    assert "schema file not found" in proc.stderr.lower()
