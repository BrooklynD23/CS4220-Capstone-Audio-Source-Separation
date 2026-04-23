from __future__ import annotations

from pathlib import Path

from live_runtime.contracts import load_live_runtime_schema, validate_live_runtime_result
from live_runtime.live_core import (
    DEFAULT_MODEL_PATH,
    DEMUCS_MODEL_PATH,
    build_live_runtime_result,
    resolve_live_model_path,
)
from live_runtime.source_ingest import build_mp3_source_ingest


FIXTURE_MP3 = Path("fixtures/audio/demo_mix.mp3")
UNSUPPORTED_MODEL_PATH = "artifacts/models/unsupported-live.pt"


def test_supported_demucs_model_path_is_not_fallbacked() -> None:
    resolution = resolve_live_model_path(DEMUCS_MODEL_PATH)

    assert resolution.requested_model_path == DEMUCS_MODEL_PATH
    assert resolution.model_path == DEMUCS_MODEL_PATH
    assert resolution.fallback_applied is False

    envelope = build_mp3_source_ingest(FIXTURE_MP3)
    payload = build_live_runtime_result(
        envelope,
        chunk_duration_s=0.5,
        target_sample_rate_hz=22050,
        model_path=DEMUCS_MODEL_PATH,
    ).to_dict()

    schema = load_live_runtime_schema()
    validate_live_runtime_result(payload, schema=schema)

    assert payload["status"] == "ok"
    assert payload["error_stage"] is None
    assert payload["error_message"] is None
    assert payload["health_state"] == "healthy"
    assert payload["health_reason"] == "runtime operating normally"
    assert payload["requested_model_path"] == DEMUCS_MODEL_PATH
    assert payload["fallback_applied"] is False
    assert payload["model_path"] == DEMUCS_MODEL_PATH
    assert payload["stem_paths"] == {
        "vocals": "artifacts/live/smoke/vocals.wav",
        "drums": "artifacts/live/smoke/drums.wav",
        "bass": "artifacts/live/smoke/bass.wav",
        "other": "artifacts/live/smoke/other.wav",
    }


def test_unsupported_model_path_still_falls_back_with_visible_health_telemetry() -> None:
    resolution = resolve_live_model_path(UNSUPPORTED_MODEL_PATH)

    assert resolution.requested_model_path == UNSUPPORTED_MODEL_PATH
    assert resolution.model_path == DEFAULT_MODEL_PATH
    assert resolution.fallback_applied is True

    envelope = build_mp3_source_ingest(FIXTURE_MP3)
    payload = build_live_runtime_result(
        envelope,
        chunk_duration_s=0.5,
        target_sample_rate_hz=22050,
        model_path=UNSUPPORTED_MODEL_PATH,
    ).to_dict()

    schema = load_live_runtime_schema()
    validate_live_runtime_result(payload, schema=schema)

    assert payload["status"] == "ok"
    assert payload["error_stage"] is None
    assert payload["error_message"] is None
    assert payload["health_state"] == "fallback"
    assert UNSUPPORTED_MODEL_PATH in str(payload["health_reason"])
    assert DEFAULT_MODEL_PATH in str(payload["health_reason"])
    assert payload["requested_model_path"] == UNSUPPORTED_MODEL_PATH
    assert payload["fallback_applied"] is True
    assert payload["model_path"] == DEFAULT_MODEL_PATH
