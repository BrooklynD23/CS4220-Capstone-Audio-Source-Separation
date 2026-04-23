from __future__ import annotations

from pathlib import Path

import pytest
from jsonschema import ValidationError

from live_runtime.contracts import (
    SCHEMA_PATH,
    load_live_runtime_schema,
    validate_live_runtime_result,
)


def build_live_runtime_payload(
    *,
    status: str = "ok",
    error_stage: str | None = None,
    error_message: str | None = None,
    health_state: str = "healthy",
    health_reason: str = "runtime operating normally",
    requested_model_path: str = "artifacts/models/umx-live.pt",
    fallback_applied: bool = False,
    model_path: str = "artifacts/models/umx-live.pt",
) -> dict[str, object]:
    return {
        "source": {
            "kind": "mp3",
            "reference": "fixtures/audio/demo_mix.mp3",
        },
        "input": "fixtures/audio/demo_mix.mp3",
        "sample_rate_hz": 44100,
        "chunk_duration_s": 1.0,
        "stft_ms": 12.5,
        "infer_ms": 98.0,
        "istft_ms": 11.75,
        "total_ms": 122.25,
        "status": status,
        "error_stage": error_stage,
        "error_message": error_message,
        "timestamp": "2026-04-20T08:09:30Z",
        "health_state": health_state,
        "health_reason": health_reason,
        "requested_model_path": requested_model_path,
        "fallback_applied": fallback_applied,
        "chunk_index": 0,
        "queue_depth": 0,
        "drop_count": 0,
        "model_path": model_path,
        "stem_paths": {
            "vocals": "artifacts/live/smoke/vocals.wav",
            "drums": "artifacts/live/smoke/drums.wav",
            "bass": "artifacts/live/smoke/bass.wav",
            "other": "artifacts/live/smoke/other.wav",
        },
        "metadata": {
            "device_requested": "gpu",
            "device_used": "gpu",
            "mode": "smoke",
            "clock_source": "perf_counter",
            "clock_fallback": False,
            "samples_processed": 44100,
            "channels": 2,
            "sample_width_bytes": 2,
            "stages": ["stft", "infer", "istft"],
        },
    }


@pytest.mark.parametrize(
    ("status", "health_state", "health_reason", "requested_model_path", "fallback_applied", "model_path"),
    [
        (
            "ok",
            "healthy",
            "runtime operating normally",
            "artifacts/models/umx-live.pt",
            False,
            "artifacts/models/umx-live.pt",
        ),
        (
            "ok",
            "degraded",
            "backpressure degraded after 64 queued chunks; dropped 1 additional chunks",
            "artifacts/models/umx-live.pt",
            False,
            "artifacts/models/umx-live.pt",
        ),
    (
            "ok",
            "fallback",
            "requested model path artifacts/models/unsupported-live.pt fell back to artifacts/models/umx-live.pt",
            "artifacts/models/unsupported-live.pt",
            True,
            "artifacts/models/umx-live.pt",
        ),
    ],
)
def test_live_runtime_schema_validates_health_aware_artifacts(
    status: str,
    health_state: str,
    health_reason: str,
    requested_model_path: str,
    fallback_applied: bool,
    model_path: str,
) -> None:
    schema = load_live_runtime_schema(SCHEMA_PATH)

    payload = build_live_runtime_payload(
        status=status,
        health_state=health_state,
        health_reason=health_reason,
        requested_model_path=requested_model_path,
        fallback_applied=fallback_applied,
        model_path=model_path,
    )

    validated = validate_live_runtime_result(payload, schema=schema)

    assert validated == payload
    assert sorted(payload["stem_paths"].keys()) == ["bass", "drums", "other", "vocals"]
    assert payload["status"] == status
    assert payload["health_state"] == health_state
    assert payload["health_reason"] == health_reason
    assert payload["requested_model_path"] == requested_model_path
    assert payload["fallback_applied"] is fallback_applied
    assert payload["model_path"] == model_path


@pytest.mark.parametrize(
    "missing_field",
    ["health_state", "health_reason", "requested_model_path", "fallback_applied"],
)
def test_live_runtime_schema_rejects_missing_health_fields(missing_field: str) -> None:
    schema = load_live_runtime_schema(SCHEMA_PATH)

    payload = build_live_runtime_payload()
    payload.pop(missing_field)

    with pytest.raises(ValidationError) as exc_info:
        validate_live_runtime_result(payload, schema=schema)

    assert missing_field in str(exc_info.value)


def test_live_runtime_schema_rejects_invalid_health_state_value() -> None:
    schema = load_live_runtime_schema(SCHEMA_PATH)

    payload = build_live_runtime_payload(health_state="fallback-ready")

    with pytest.raises(ValidationError) as exc_info:
        validate_live_runtime_result(payload, schema=schema)

    assert "health_state" in str(exc_info.value)


def test_live_runtime_schema_rejects_missing_source_metadata() -> None:
    schema = load_live_runtime_schema(SCHEMA_PATH)

    payload = build_live_runtime_payload()
    payload.pop("source")

    with pytest.raises(ValidationError) as exc_info:
        validate_live_runtime_result(payload, schema=schema)

    assert "source" in str(exc_info.value)


def test_live_runtime_schema_rejects_empty_source_reference() -> None:
    schema = load_live_runtime_schema(SCHEMA_PATH)

    payload = build_live_runtime_payload()
    payload["source"] = {"kind": "mp3", "reference": ""}

    with pytest.raises(ValidationError) as exc_info:
        validate_live_runtime_result(payload, schema=schema)

    assert "reference" in str(exc_info.value)


def test_live_runtime_schema_rejects_missing_s01_timing_field() -> None:
    schema = load_live_runtime_schema(SCHEMA_PATH)

    payload = build_live_runtime_payload()
    payload.pop("stft_ms")

    with pytest.raises(ValidationError) as exc_info:
        validate_live_runtime_result(payload, schema=schema)

    assert "stft_ms" in str(exc_info.value)


def test_live_runtime_schema_rejects_malformed_metadata_types() -> None:
    schema = load_live_runtime_schema(SCHEMA_PATH)

    payload = build_live_runtime_payload()
    payload["queue_depth"] = "two"

    with pytest.raises(ValidationError) as exc_info:
        validate_live_runtime_result(payload, schema=schema)

    assert "queue_depth" in str(exc_info.value)


def test_live_runtime_schema_rejects_malformed_stage_timing_types() -> None:
    schema = load_live_runtime_schema(SCHEMA_PATH)

    payload = build_live_runtime_payload()
    payload["stft_ms"] = "fast"

    with pytest.raises(ValidationError) as exc_info:
        validate_live_runtime_result(payload, schema=schema)

    assert "stft_ms" in str(exc_info.value)



def test_live_runtime_schema_rejects_legacy_two_stem_shape() -> None:
    schema = load_live_runtime_schema(SCHEMA_PATH)

    payload = build_live_runtime_payload()
    payload["stem_paths"] = {
        "vocals": "artifacts/live/smoke/vocals.wav",
        "instrumental": "artifacts/live/smoke/instrumental.wav",
    }

    with pytest.raises(ValidationError) as exc_info:
        validate_live_runtime_result(payload, schema=schema)

    assert "stem_paths" in str(exc_info.value)


@pytest.mark.parametrize(
    "stem_paths",
    [
        {"vocals": "artifacts/live/smoke/vocals.wav", "drums": "artifacts/live/smoke/drums.wav", "bass": "artifacts/live/smoke/bass.wav"},
        {"vocals": "artifacts/live/smoke/vocals.wav", "drums": "artifacts/live/smoke/drums.wav", "bass": "artifacts/live/smoke/bass.wav", "other": "artifacts/live/smoke/other.wav", "instrumental": "artifacts/live/smoke/instrumental.wav"},
        [],
        {},
    ],
)
def test_live_runtime_schema_rejects_non_canonical_stem_path_shapes(stem_paths: object) -> None:
    schema = load_live_runtime_schema(SCHEMA_PATH)

    payload = build_live_runtime_payload()
    payload["stem_paths"] = stem_paths

    with pytest.raises(ValidationError) as exc_info:
        validate_live_runtime_result(payload, schema=schema)

    assert "stem_paths" in str(exc_info.value)


def test_live_runtime_schema_rejects_empty_schema_file(tmp_path: Path) -> None:
    empty_schema = tmp_path / "empty-live-runtime.schema.json"
    empty_schema.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_live_runtime_schema(empty_schema)

    assert str(empty_schema) in str(exc_info.value)


def test_live_runtime_schema_reports_missing_schema_file(tmp_path: Path) -> None:
    missing_schema = tmp_path / "missing-live-runtime.schema.json"

    with pytest.raises(FileNotFoundError) as exc_info:
        load_live_runtime_schema(missing_schema)

    assert str(missing_schema) in str(exc_info.value)
