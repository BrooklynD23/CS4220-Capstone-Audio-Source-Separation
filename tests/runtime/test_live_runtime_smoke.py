from __future__ import annotations

import importlib.abc
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from live_runtime.contracts import load_live_runtime_schema, validate_live_runtime_result
from live_runtime.live_core import DEFAULT_MODEL_PATH

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLI_SCRIPT = PROJECT_ROOT / "scripts/live/run_live_separation.py"
FIXTURE_MP3 = PROJECT_ROOT / "fixtures/audio/demo_mix.mp3"
FIXTURE_VIDEO = PROJECT_ROOT / "fixtures/video/demo_mix.mp4"
UNSUPPORTED_MODEL_PATH = "artifacts/models/unsupported-live.pt"
SCHEMA_PATH = PROJECT_ROOT / "artifacts/schema/live_runtime_result.schema.json"


class _BlockedUmxImport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object | None, target: object | None = None) -> object | None:
        if fullname == "live_runtime.umx_separator":
            raise AssertionError("smoke CLI import must not import live_runtime.umx_separator")
        return None


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(CLI_SCRIPT), *args]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_live_cli_module_import_does_not_import_optional_umx_runtime(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "live_runtime.umx_separator", raising=False)
    blocker = _BlockedUmxImport()
    sys.meta_path.insert(0, blocker)
    try:
        spec = importlib.util.spec_from_file_location("run_live_separation_import_guard", CLI_SCRIPT)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.meta_path.remove(blocker)


def test_live_cli_full_mode_reports_missing_umx_runtime_as_actionable_artifact(monkeypatch, tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("run_live_separation_full_guard", CLI_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def _raise_missing_runtime():
        raise RuntimeError("Full mode requires optional GPU dependencies: torch, torchaudio, openunmix.")

    monkeypatch.setattr(module, "_load_umx_runtime", _raise_missing_runtime)

    output_dir = tmp_path / "full-missing-runtime"
    payload, exit_code, ingest = module._build_artifact(
        source_mode="mp3",
        input_path=FIXTURE_MP3,
        output_dir=output_dir,
        sample_rate_hz=22050,
        chunk_duration_s=0.5,
        max_queue_depth=64,
        decode_timeout_s=30.0,
        device_requested="gpu",
        device_used="cpu",
        mode="full",
        model_path=DEFAULT_MODEL_PATH,
        mic_backend="fake",
        mic_device="fixture:mic-demo",
        capture_duration_s=1.0,
    )

    assert exit_code == 1
    assert ingest is None
    assert payload["status"] == "error"
    assert payload["error_stage"] == "model_load_failed"
    assert "optional GPU dependencies" in str(payload["error_message"])
    assert payload["metadata"]["mode"] == "full"


def test_live_cli_smoke_writes_schema_valid_runtime_artifact_and_four_stems(tmp_path: Path) -> None:
    output_dir = tmp_path / "smoke-run"
    artifact_path = output_dir / "live_runtime_result.json"

    proc = _run_cli(
        "--input",
        str(FIXTURE_MP3),
        "--output-dir",
        str(output_dir),
        "--artifact-path",
        str(artifact_path),
        "--chunk-duration-s",
        "0.5",
        "--sample-rate-hz",
        "22050",
        "--max-queue-depth",
        "64",
    )

    assert proc.returncode == 0, proc.stderr
    assert artifact_path.exists(), proc.stdout

    payload = _load_json(artifact_path)
    schema = load_live_runtime_schema(SCHEMA_PATH)
    validate_live_runtime_result(payload, schema=schema)

    assert payload["status"] == "ok"
    assert payload["error_stage"] is None
    assert payload["error_message"] is None
    assert payload["health_state"] == "healthy"
    assert payload["health_reason"] == "runtime operating normally"
    assert payload["requested_model_path"] == DEFAULT_MODEL_PATH
    assert payload["fallback_applied"] is False
    assert payload["model_path"] == DEFAULT_MODEL_PATH
    assert payload["source"]["kind"] == "mp3"
    assert payload["source"]["reference"] == str(FIXTURE_MP3)
    assert sorted(payload["stem_paths"].keys()) == ["bass", "drums", "other", "vocals"]
    assert payload["stem_paths"]["vocals"] == str(output_dir / "vocals.wav")
    assert payload["stem_paths"]["drums"] == str(output_dir / "drums.wav")
    assert payload["stem_paths"]["bass"] == str(output_dir / "bass.wav")
    assert payload["stem_paths"]["other"] == str(output_dir / "other.wav")
    assert (output_dir / "vocals.wav").exists()
    assert (output_dir / "drums.wav").exists()
    assert (output_dir / "bass.wav").exists()
    assert (output_dir / "other.wav").exists()

    stem_outputs = sorted(output_dir.glob("*.wav"))
    assert [path.name for path in stem_outputs] == ["bass.wav", "drums.wav", "other.wav", "vocals.wav"]
    assert all(path.stat().st_size > 0 for path in stem_outputs)


def test_live_cli_overload_reports_degraded_health_and_writes_stems(tmp_path: Path) -> None:
    output_dir = tmp_path / "degraded-run"
    artifact_path = output_dir / "live_runtime_result.json"

    proc = _run_cli(
        "--input",
        str(FIXTURE_MP3),
        "--output-dir",
        str(output_dir),
        "--artifact-path",
        str(artifact_path),
        "--chunk-duration-s",
        "0.5",
        "--sample-rate-hz",
        "22050",
        "--max-queue-depth",
        "3",
    )

    assert proc.returncode == 0, proc.stderr
    assert artifact_path.exists(), proc.stdout

    payload = _load_json(artifact_path)
    schema = load_live_runtime_schema(SCHEMA_PATH)
    validate_live_runtime_result(payload, schema=schema)

    assert payload["status"] == "ok"
    assert payload["error_stage"] is None
    assert payload["error_message"] is None
    assert payload["health_state"] == "degraded"
    assert "dropped 17 additional chunks" in str(payload["health_reason"])
    assert payload["requested_model_path"] == DEFAULT_MODEL_PATH
    assert payload["fallback_applied"] is False
    assert payload["model_path"] == DEFAULT_MODEL_PATH
    assert payload["queue_depth"] == 3
    assert payload["drop_count"] == 17
    assert sorted(payload["stem_paths"].keys()) == ["bass", "drums", "other", "vocals"]
    assert payload["stem_paths"]["vocals"] == str(output_dir / "vocals.wav")
    assert payload["stem_paths"]["drums"] == str(output_dir / "drums.wav")
    assert payload["stem_paths"]["bass"] == str(output_dir / "bass.wav")
    assert payload["stem_paths"]["other"] == str(output_dir / "other.wav")
    assert (output_dir / "vocals.wav").exists()
    assert (output_dir / "drums.wav").exists()
    assert (output_dir / "bass.wav").exists()
    assert (output_dir / "other.wav").exists()


def test_live_cli_model_path_fallback_writes_schema_valid_runtime_artifact_and_four_stems(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "fallback-run"
    artifact_path = output_dir / "live_runtime_result.json"
    requested_model_path = UNSUPPORTED_MODEL_PATH

    proc = _run_cli(
        "--input",
        str(FIXTURE_MP3),
        "--model-path",
        requested_model_path,
        "--output-dir",
        str(output_dir),
        "--artifact-path",
        str(artifact_path),
        "--chunk-duration-s",
        "0.5",
        "--sample-rate-hz",
        "22050",
    )

    assert proc.returncode == 0, proc.stderr
    assert artifact_path.exists(), proc.stdout

    payload = _load_json(artifact_path)
    schema = load_live_runtime_schema(SCHEMA_PATH)
    validate_live_runtime_result(payload, schema=schema)

    assert payload["status"] == "ok"
    assert payload["error_stage"] is None
    assert payload["error_message"] is None
    assert payload["health_state"] == "fallback"
    assert requested_model_path in str(payload["health_reason"])
    assert DEFAULT_MODEL_PATH in str(payload["health_reason"])
    assert payload["requested_model_path"] == requested_model_path
    assert payload["fallback_applied"] is True
    assert payload["model_path"] == DEFAULT_MODEL_PATH
    assert sorted(payload["stem_paths"].keys()) == ["bass", "drums", "other", "vocals"]
    assert payload["stem_paths"]["vocals"] == str(output_dir / "vocals.wav")
    assert payload["stem_paths"]["drums"] == str(output_dir / "drums.wav")
    assert payload["stem_paths"]["bass"] == str(output_dir / "bass.wav")
    assert payload["stem_paths"]["other"] == str(output_dir / "other.wav")
    assert (output_dir / "vocals.wav").exists()
    assert (output_dir / "drums.wav").exists()
    assert (output_dir / "bass.wav").exists()
    assert (output_dir / "other.wav").exists()


def test_live_cli_can_rerun_into_the_same_output_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "rerun-run"
    artifact_path = output_dir / "live_runtime_result.json"

    first = _run_cli(
        "--input",
        str(FIXTURE_MP3),
        "--output-dir",
        str(output_dir),
        "--artifact-path",
        str(artifact_path),
    )
    second = _run_cli(
        "--input",
        str(FIXTURE_MP3),
        "--output-dir",
        str(output_dir),
        "--artifact-path",
        str(artifact_path),
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    payload = _load_json(artifact_path)
    assert payload["status"] == "ok"
    assert payload["source"]["kind"] == "mp3"
    assert payload["source"]["reference"] == str(FIXTURE_MP3)
    assert sorted(path.name for path in output_dir.glob("*.wav")) == ["bass.wav", "drums.wav", "other.wav", "vocals.wav"]


def test_live_cli_video_audio_mode_writes_schema_valid_runtime_artifact_and_four_stems(tmp_path: Path) -> None:
    output_dir = tmp_path / "video-run"
    artifact_path = output_dir / "live_runtime_result.json"

    proc = _run_cli(
        "--source-mode",
        "video-audio",
        "--output-dir",
        str(output_dir),
        "--artifact-path",
        str(artifact_path),
        "--chunk-duration-s",
        "0.5",
        "--sample-rate-hz",
        "22050",
    )

    assert proc.returncode == 0, proc.stderr
    assert artifact_path.exists(), proc.stdout

    payload = _load_json(artifact_path)
    schema = load_live_runtime_schema(SCHEMA_PATH)
    validate_live_runtime_result(payload, schema=schema)

    assert payload["status"] == "ok"
    assert payload["source"]["kind"] == "video_audio"
    assert payload["source"]["reference"] == str(FIXTURE_VIDEO)
    assert payload["source"]["metadata"]["container"] == "mp4"
    assert sorted(payload["stem_paths"].keys()) == ["bass", "drums", "other", "vocals"]
    assert payload["stem_paths"]["vocals"] == str(output_dir / "vocals.wav")
    assert payload["stem_paths"]["drums"] == str(output_dir / "drums.wav")
    assert payload["stem_paths"]["bass"] == str(output_dir / "bass.wav")
    assert payload["stem_paths"]["other"] == str(output_dir / "other.wav")
    assert sorted(path.name for path in output_dir.glob("*.wav")) == ["bass.wav", "drums.wav", "other.wav", "vocals.wav"]


def test_live_cli_mic_mode_with_fake_backend_writes_schema_valid_runtime_artifact_and_four_stems(tmp_path: Path) -> None:
    output_dir = tmp_path / "mic-run"
    artifact_path = output_dir / "live_runtime_result.json"

    proc = _run_cli(
        "--source-mode",
        "mic",
        "--mic-backend",
        "fake",
        "--mic-device",
        "fixture:mic-demo",
        "--output-dir",
        str(output_dir),
        "--artifact-path",
        str(artifact_path),
        "--chunk-duration-s",
        "0.5",
        "--sample-rate-hz",
        "22050",
    )

    assert proc.returncode == 0, proc.stderr
    assert artifact_path.exists(), proc.stdout

    payload = _load_json(artifact_path)
    schema = load_live_runtime_schema(SCHEMA_PATH)
    validate_live_runtime_result(payload, schema=schema)

    assert payload["status"] == "ok"
    assert payload["source"]["kind"] == "mic"
    assert payload["source"]["reference"] == "fixture:mic-demo"
    assert payload["source"]["metadata"]["backend"] == "fake"
    assert payload["source"]["metadata"]["device"] == "fixture:mic-demo"
    assert sorted(payload["stem_paths"].keys()) == ["bass", "drums", "other", "vocals"]
    assert payload["stem_paths"]["vocals"] == str(output_dir / "vocals.wav")
    assert payload["stem_paths"]["drums"] == str(output_dir / "drums.wav")
    assert payload["stem_paths"]["bass"] == str(output_dir / "bass.wav")
    assert payload["stem_paths"]["other"] == str(output_dir / "other.wav")
    assert sorted(path.name for path in output_dir.glob("*.wav")) == ["bass.wav", "drums.wav", "other.wav", "vocals.wav"]


def test_live_cli_missing_input_reports_decode_failure_and_preserves_artifact(tmp_path: Path) -> None:
    output_dir = tmp_path / "missing-input"
    artifact_path = tmp_path / "missing-input-artifact.json"

    proc = _run_cli(
        "--input",
        str(tmp_path / "missing.mp3"),
        "--output-dir",
        str(output_dir),
        "--artifact-path",
        str(artifact_path),
    )

    assert proc.returncode != 0
    assert artifact_path.exists()

    payload = _load_json(artifact_path)
    schema = load_live_runtime_schema(SCHEMA_PATH)
    validate_live_runtime_result(payload, schema=schema)

    assert payload["status"] == "error"
    assert payload["error_stage"] == "decode_failed"
    assert payload["health_state"] == "degraded"
    assert payload["requested_model_path"] == DEFAULT_MODEL_PATH
    assert payload["fallback_applied"] is False
    assert payload["model_path"] == DEFAULT_MODEL_PATH
    assert "missing.mp3" in str(payload["error_message"])
    assert not list(output_dir.glob("*.wav"))


def test_live_cli_rejects_invalid_output_directory_and_keeps_artifact(tmp_path: Path) -> None:
    output_dir = tmp_path / "blocked-output"
    output_dir.write_text("not a directory", encoding="utf-8")
    artifact_path = tmp_path / "blocked-output-artifact.json"

    proc = _run_cli(
        "--input",
        str(FIXTURE_MP3),
        "--output-dir",
        str(output_dir),
        "--artifact-path",
        str(artifact_path),
    )

    assert proc.returncode != 0
    assert artifact_path.exists()

    payload = _load_json(artifact_path)
    schema = load_live_runtime_schema(SCHEMA_PATH)
    validate_live_runtime_result(payload, schema=schema)

    assert payload["status"] == "error"
    assert payload["error_stage"] == "output_write_failed"
    assert payload["health_state"] == "degraded"
    assert payload["requested_model_path"] == DEFAULT_MODEL_PATH
    assert payload["fallback_applied"] is False
    assert payload["model_path"] == DEFAULT_MODEL_PATH
    assert "not writable" in str(payload["error_message"])
