from __future__ import annotations

from pathlib import Path

import pytest
from jsonschema import ValidationError

from live_runtime.contracts import load_live_runtime_schema, validate_live_runtime_result
from live_runtime.live_core import DEFAULT_MODEL_PATH, build_live_runtime_result, resolve_live_model_path
from live_runtime.source_ingest import build_mp3_source_ingest


FIXTURE_MP3 = Path("fixtures/audio/demo_mix.mp3")
UNSUPPORTED_MODEL_PATH = "artifacts/models/unsupported-live.pt"


def test_resolve_live_model_path_keeps_the_stable_model_path_for_default_requests() -> None:
    resolution = resolve_live_model_path(DEFAULT_MODEL_PATH)

    assert resolution.requested_model_path == DEFAULT_MODEL_PATH
    assert resolution.model_path == DEFAULT_MODEL_PATH
    assert resolution.fallback_applied is False


def test_resolve_live_model_path_falls_back_to_the_stable_model_path_for_unsupported_requests() -> None:
    requested_model_path = UNSUPPORTED_MODEL_PATH

    resolution = resolve_live_model_path(requested_model_path)

    assert resolution.requested_model_path == requested_model_path
    assert resolution.model_path == DEFAULT_MODEL_PATH
    assert resolution.fallback_applied is True


def test_live_runtime_result_marks_overload_as_degraded_without_hard_error() -> None:
    envelope = build_mp3_source_ingest(
        FIXTURE_MP3,
        chunk_duration_s=0.5,
        target_sample_rate_hz=22050,
        max_queue_depth=3,
    )
    result = build_live_runtime_result(
        envelope,
        chunk_duration_s=0.5,
        target_sample_rate_hz=22050,
        max_queue_depth=3,
    )

    payload = result.to_dict()
    schema = load_live_runtime_schema()
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
    assert payload["chunk_index"] == 19
    assert payload["metadata"]["samples_processed"] == 220500
    assert payload["metadata"]["stages"] == ["stft", "infer", "istft"]
    assert payload["source"]["kind"] == "mp3"
    assert payload["source"]["reference"] == str(FIXTURE_MP3)


def test_live_runtime_result_marks_higher_risk_model_paths_as_fallbacks() -> None:
    envelope = build_mp3_source_ingest(
        FIXTURE_MP3,
        chunk_duration_s=0.5,
        target_sample_rate_hz=22050,
    )
    requested_model_path = UNSUPPORTED_MODEL_PATH
    result = build_live_runtime_result(
        envelope,
        chunk_duration_s=0.5,
        target_sample_rate_hz=22050,
        model_path=requested_model_path,
    )

    payload = result.to_dict()
    schema = load_live_runtime_schema()
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
    assert payload["queue_depth"] == 20
    assert payload["drop_count"] == 0


def test_live_runtime_schema_rejects_invalid_fallback_shape() -> None:
    schema = load_live_runtime_schema()

    envelope = build_mp3_source_ingest(FIXTURE_MP3)
    payload = build_live_runtime_result(
        envelope,
        chunk_duration_s=0.5,
        target_sample_rate_hz=22050,
    ).to_dict()
    payload.pop("requested_model_path")

    with pytest.raises(ValidationError) as exc_info:
        validate_live_runtime_result(payload, schema=schema)

    assert "requested_model_path" in str(exc_info.value)
