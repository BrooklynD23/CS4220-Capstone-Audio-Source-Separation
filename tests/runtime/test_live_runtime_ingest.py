from __future__ import annotations

from pathlib import Path

import pytest

from live_runtime.contracts import HealthTelemetry, load_live_runtime_schema, validate_live_runtime_result
from live_runtime.live_core import build_live_runtime_result
from live_runtime.mic_ingest import (
    CapturedMicAudio,
    FakeMicCaptureBackend,
    MicCaptureFailedError,
    SoundDeviceMicCaptureBackend,
    build_mic_source_ingest,
)
from live_runtime.mp3_ingest import DecodedAudio
from live_runtime.source_ingest import (
    SourceDescriptor,
    SourceIngestEnvelope,
    build_mp3_source_ingest,
)
from live_runtime.stem_router import StemRoutingError, write_live_stems, write_live_stems_from_arrays


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


def test_source_descriptor_rejects_unsupported_kind() -> None:
    with pytest.raises(ValueError, match="unsupported source kind"):
        SourceDescriptor(kind="stream", reference="fixture:stream")  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", ["mic", "video_audio"])
def test_source_descriptor_rejects_missing_kind_specific_metadata(kind: str) -> None:
    with pytest.raises(ValueError, match="metadata"):
        SourceDescriptor(kind=kind, reference=f"{kind}:demo")


@pytest.mark.parametrize(
    ("health_state", "health_reason", "requested_model_path", "message"),
    [
        ("unknown", "runtime operating normally", "artifacts/models/umx-live.pt", "health state"),
        ("healthy", "", "artifacts/models/umx-live.pt", "health reason"),
        ("healthy", "runtime operating normally", "", "requested model path"),
    ],
)
def test_health_telemetry_rejects_invalid_required_fields(
    health_state: str,
    health_reason: str,
    requested_model_path: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        HealthTelemetry(
            health_state=health_state,  # type: ignore[arg-type]
            health_reason=health_reason,
            requested_model_path=requested_model_path,
            fallback_applied=False,
        )


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


def test_live_core_logs_degraded_health_state(caplog: pytest.LogCaptureFixture) -> None:
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

    assert result.health.health_state == "degraded"
    assert any(record.levelname == "WARNING" for record in caplog.records)
    assert any("degraded" in record.getMessage() for record in caplog.records)


def test_live_core_rejects_chunk_requests_larger_than_allowed_boundary() -> None:
    envelope = build_mp3_source_ingest(FIXTURE_MP3)

    with pytest.raises(ValueError, match="chunk_duration_s"):
        build_live_runtime_result(
            envelope,
            chunk_duration_s=31.0,
            target_sample_rate_hz=22050,
        )


def test_live_core_rejects_empty_decoded_sources() -> None:
    decoded = DecodedAudio(
        source_path=FIXTURE_MP3,
        sample_rate_hz=22050,
        channels=1,
        sample_width_bytes=2,
        chunk_duration_s=0.5,
        total_frames=0,
        pcm=b"",
        chunks=(),
    )
    envelope = SourceIngestEnvelope(
        source=SourceDescriptor(kind="mp3", reference=str(FIXTURE_MP3)),
        decoded_audio=decoded,
        ingest_ms=0.0,
    )

    with pytest.raises(ValueError, match="no chunks"):
        build_live_runtime_result(envelope, chunk_duration_s=0.5, target_sample_rate_hz=22050)


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


def test_write_live_mix_wav_writes_readable_wav_chunk(tmp_path: Path) -> None:
    """mix.wav complements stem outputs so the compare shell can PCM-decode Input."""

    output_dir = tmp_path / "mix-out"
    pcm = bytes(256)  # 128 mono s16 silent samples
    from live_runtime.stem_router import write_live_mix_wav

    wrote = write_live_mix_wav(output_dir, sample_rate_hz=44100, pcm=pcm)
    assert wrote == output_dir / "mix.wav"
    assert wrote.is_file()


def test_write_live_stems_logs_each_stem_write(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG", logger="live_runtime.stem_router")
    envelope = build_mp3_source_ingest(FIXTURE_MP3, chunk_duration_s=0.5)

    write_live_stems(envelope, tmp_path / "stems")

    messages = [record.getMessage() for record in caplog.records]
    for stem_name in ("vocals", "drums", "bass", "other"):
        assert any(stem_name in message for message in messages)


def test_write_live_stems_rejects_unaligned_decoded_pcm(tmp_path: Path) -> None:
    decoded = DecodedAudio(
        source_path=FIXTURE_MP3,
        sample_rate_hz=22050,
        channels=1,
        sample_width_bytes=2,
        chunk_duration_s=0.5,
        total_frames=1,
        pcm=b"\x00",
        chunks=(),
    )
    envelope = SourceIngestEnvelope(
        source=SourceDescriptor(kind="mp3", reference=str(FIXTURE_MP3)),
        decoded_audio=decoded,
        ingest_ms=0.0,
    )

    with pytest.raises(StemRoutingError, match="frame aligned"):
        write_live_stems(envelope, tmp_path / "stems")


def test_write_live_stems_from_arrays_writes_four_wavs(tmp_path: Path) -> None:
    import numpy as np

    routing = write_live_stems_from_arrays(
        {
            "vocals": np.array([[0.0, 0.5, -0.5]], dtype=np.float32),
            "drums": np.array([0.25, -0.25, 0.0], dtype=np.float32),
        },
        tmp_path / "array-stems",
        22050,
    )

    assert Path(routing.vocals_path).exists()
    assert Path(routing.drums_path).exists()
    assert Path(routing.bass_path).exists()
    assert Path(routing.other_path).exists()
    assert sorted(path.name for path in (tmp_path / "array-stems").glob("*.wav")) == [
        "bass.wav",
        "drums.wav",
        "other.wav",
        "vocals.wav",
    ]


def test_fake_mic_backend_rejects_non_positive_timeout() -> None:
    backend = FakeMicCaptureBackend()

    with pytest.raises(ValueError, match="capture_timeout_s"):
        backend.capture(
            "fixture:mic-demo",
            sample_rate_hz=22050,
            capture_duration_s=1.0,
            capture_timeout_s=0.0,
        )


def test_sounddevice_backend_rejects_invalid_capture_inputs_before_import() -> None:
    backend = SoundDeviceMicCaptureBackend()

    with pytest.raises(MicCaptureFailedError, match="sample_rate_hz"):
        backend.capture(
            "default",
            sample_rate_hz=0,
            capture_duration_s=1.0,
            capture_timeout_s=1.0,
        )

    with pytest.raises(MicCaptureFailedError, match="capture_duration_s"):
        backend.capture(
            "default",
            sample_rate_hz=22050,
            capture_duration_s=0.0,
            capture_timeout_s=1.0,
        )


class _StaticMicBackend:
    backend_name = "static"

    def __init__(self, captured: CapturedMicAudio) -> None:
        self._captured = captured

    def capture(
        self,
        device_reference: str,
        *,
        sample_rate_hz: int,
        capture_duration_s: float,
        capture_timeout_s: float,
    ) -> CapturedMicAudio:
        return self._captured


def test_mic_source_ingest_rejects_unsupported_capture_format() -> None:
    backend = _StaticMicBackend(
        CapturedMicAudio(
            pcm=b"\x00\x00",
            sample_rate_hz=22050,
            channels=2,
            sample_width_bytes=2,
            backend_name="static",
            device_reference="fixture:mic-demo",
            capture_duration_s=1.0,
        )
    )

    with pytest.raises(MicCaptureFailedError, match="unsupported capture format"):
        build_mic_source_ingest(
            "fixture:mic-demo",
            backend=backend,
            target_sample_rate_hz=22050,
        )


def test_mic_source_ingest_rejects_backend_sample_rate_mismatch() -> None:
    backend = _StaticMicBackend(
        CapturedMicAudio(
            pcm=b"\x00\x00",
            sample_rate_hz=44100,
            channels=1,
            sample_width_bytes=2,
            backend_name="static",
            device_reference="fixture:mic-demo",
            capture_duration_s=1.0,
        )
    )

    with pytest.raises(MicCaptureFailedError, match="sample_rate_hz"):
        build_mic_source_ingest(
            "fixture:mic-demo",
            backend=backend,
            target_sample_rate_hz=22050,
        )


def test_mic_source_ingest_wraps_decode_failures() -> None:
    backend = _StaticMicBackend(
        CapturedMicAudio(
            pcm=b"",
            sample_rate_hz=22050,
            channels=1,
            sample_width_bytes=2,
            backend_name="static",
            device_reference="fixture:mic-demo",
            capture_duration_s=1.0,
        )
    )

    with pytest.raises(MicCaptureFailedError, match="contained no frames"):
        build_mic_source_ingest(
            "fixture:mic-demo",
            backend=backend,
            target_sample_rate_hz=22050,
        )
