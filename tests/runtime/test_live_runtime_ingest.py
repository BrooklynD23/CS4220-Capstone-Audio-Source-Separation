from __future__ import annotations

from pathlib import Path

import pytest
from jsonschema import ValidationError

from live_runtime.contracts import load_live_runtime_schema, validate_live_runtime_result
from live_runtime.live_core import build_live_runtime_result
from live_runtime.source_ingest import (
    SourceDescriptor,
    build_mp3_source_ingest,
)
from live_runtime.stem_router import write_live_stems


FIXTURE_MP3 = Path("fixtures/audio/demo_mix.mp3")


def test_mp3_fixture_decodes_into_deterministic_chunks() -> None:
    envelope = build_mp3_source_ingest(
        FIXTURE_MP3,
        target_sample_rate_hz=22050,
        chunk_duration_s=0.5,
    )

    decoded = envelope.decoded_audio

    assert envelope.source.kind == "mp3"
    assert envelope.source.reference == str(FIXTURE_MP3)
    assert decoded.source_path == FIXTURE_MP3
    assert decoded.sample_rate_hz == 22050
    assert decoded.channels == 1
    assert decoded.sample_width_bytes == 2
    assert decoded.chunk_duration_s == 0.5
    assert decoded.total_frames == 220500
    assert decoded.chunk_count == 20
    assert decoded.chunks[0].chunk_index == 0
    assert decoded.chunks[-1].chunk_index == 19
    assert decoded.chunks[0].queue_depth == 1
    assert decoded.chunks[-1].queue_depth == 20
    assert decoded.chunks[-1].drop_count == 0
    assert envelope.ingest_ms >= 0


@pytest.mark.parametrize("chunk_duration_s", [0, -0.25])
def test_mp3_ingest_rejects_non_positive_chunk_duration(chunk_duration_s: float) -> None:
    with pytest.raises(ValueError, match="chunk_duration_s"):
        build_mp3_source_ingest(FIXTURE_MP3, chunk_duration_s=chunk_duration_s)


def test_source_descriptor_rejects_empty_reference() -> None:
    with pytest.raises(ValueError, match="reference"):
        SourceDescriptor(kind="mp3", reference="")


@pytest.mark.parametrize("kind", ["mic", "video_audio"])
def test_source_descriptor_rejects_missing_kind_specific_metadata(kind: str) -> None:
    with pytest.raises(ValueError, match="metadata"):
        SourceDescriptor(kind=kind, reference=f"{kind}:demo")


def test_mp3_ingest_rejects_missing_path() -> None:
    with pytest.raises(FileNotFoundError, match="missing.mp3"):
        build_mp3_source_ingest(Path("fixtures/audio/missing.mp3"))


def test_mp3_ingest_rejects_corrupt_mp3(tmp_path: Path) -> None:
    corrupt_mp3 = tmp_path / "corrupt.mp3"
    corrupt_mp3.write_bytes(b"not an mp3")

    with pytest.raises(Exception) as exc_info:
        build_mp3_source_ingest(corrupt_mp3)

    assert str(corrupt_mp3) in str(exc_info.value)


def test_live_core_marks_backpressure_exhaustion_in_runtime_result() -> None:
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
    assert payload["queue_depth"] == 3
    assert payload["drop_count"] == 17
    assert payload["chunk_index"] == 19
    assert payload["metadata"]["samples_processed"] == 220500
    assert payload["metadata"]["stages"] == ["stft", "infer", "istft"]
    assert payload["source"]["kind"] == "mp3"
    assert payload["source"]["reference"] == str(FIXTURE_MP3)


def test_live_core_rejects_chunk_requests_larger_than_allowed_boundary() -> None:
    envelope = build_mp3_source_ingest(FIXTURE_MP3)

    with pytest.raises(ValueError, match="chunk_duration_s"):
        build_live_runtime_result(
            envelope,
            chunk_duration_s=31.0,
            target_sample_rate_hz=22050,
        )


def test_live_runtime_result_matches_schema_for_happy_path() -> None:
    envelope = build_mp3_source_ingest(
        FIXTURE_MP3,
        chunk_duration_s=0.5,
        target_sample_rate_hz=22050,
        max_queue_depth=64,
    )
    result = build_live_runtime_result(
        envelope,
        chunk_duration_s=0.5,
        target_sample_rate_hz=22050,
        max_queue_depth=64,
    )

    payload = result.to_dict()
    schema = load_live_runtime_schema()
    validated = validate_live_runtime_result(payload, schema=schema)

    assert validated == payload
    assert payload["status"] == "ok"
    assert payload["error_stage"] is None
    assert payload["error_message"] is None
    assert payload["queue_depth"] == 20
    assert payload["drop_count"] == 0
    assert payload["chunk_index"] == 19
    assert payload["metadata"]["clock_source"] == "ingest"
    assert payload["source"]["kind"] == "mp3"
    assert payload["source"]["reference"] == str(FIXTURE_MP3)


def test_write_live_stems_reuses_the_decoded_source_envelope(tmp_path: Path) -> None:
    envelope = build_mp3_source_ingest(FIXTURE_MP3, chunk_duration_s=0.5)
    output_dir = tmp_path / "stems"

    routing = write_live_stems(
        envelope,
        output_dir,
    )

    assert Path(routing.vocals_path).exists()
    assert Path(routing.drums_path).exists()
    assert Path(routing.bass_path).exists()
    assert Path(routing.other_path).exists()
    assert sorted(path.name for path in output_dir.glob("*.wav")) == ["bass.wav", "drums.wav", "other.wav", "vocals.wav"]
