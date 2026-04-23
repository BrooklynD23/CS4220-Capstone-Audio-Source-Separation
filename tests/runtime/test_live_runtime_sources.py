from __future__ import annotations

from pathlib import Path

import pytest

from live_runtime.contracts import load_live_runtime_schema, validate_live_runtime_result
from live_runtime.live_core import build_live_runtime_result
from live_runtime.mic_ingest import FakeMicCaptureBackend, build_mic_source_ingest
from live_runtime.mp3_ingest import DecodeFailedError
from live_runtime.source_ingest import build_mp3_source_ingest
from live_runtime.video_ingest import build_video_source_ingest
from scripts.live.run_live_separation import (
    DEFAULT_MP3_INPUT_PATH,
    DEFAULT_VIDEO_INPUT_PATH,
    _build_source_descriptor,
    parse_args,
)


FIXTURE_MP3 = Path("fixtures/audio/demo_mix.mp3")
FIXTURE_VIDEO = Path("fixtures/video/demo_mix.mp4")


def _validate_payload(payload: dict[str, object]) -> dict[str, object]:
    schema = load_live_runtime_schema()
    return validate_live_runtime_result(payload, schema=schema)


def test_cli_source_mode_selection_builds_expected_descriptors() -> None:
    mp3_descriptor = _build_source_descriptor(
        source_mode="mp3",
        input_path=None,
        mic_device="fixture:mic-demo",
        mic_backend="fake",
        capture_duration_s=1.0,
        sample_rate_hz=22050,
    )
    video_descriptor = _build_source_descriptor(
        source_mode="video-audio",
        input_path=None,
        mic_device="fixture:mic-demo",
        mic_backend="fake",
        capture_duration_s=1.0,
        sample_rate_hz=22050,
    )
    mic_descriptor = _build_source_descriptor(
        source_mode="mic",
        input_path=FIXTURE_VIDEO,
        mic_device="fixture:mic-demo",
        mic_backend="fake",
        capture_duration_s=1.0,
        sample_rate_hz=22050,
    )

    assert mp3_descriptor.kind == "mp3"
    assert mp3_descriptor.reference == str(DEFAULT_MP3_INPUT_PATH)
    assert mp3_descriptor.metadata == {}

    assert video_descriptor.kind == "video_audio"
    assert video_descriptor.reference == str(DEFAULT_VIDEO_INPUT_PATH)
    assert video_descriptor.metadata == {"container": "mp4"}

    assert mic_descriptor.kind == "mic"
    assert mic_descriptor.reference == "fixture:mic-demo"
    assert mic_descriptor.metadata == {
        "backend": "fake",
        "device": "fixture:mic-demo",
        "capture_duration_s": 1.0,
        "sample_rate_hz": 22050,
    }


def test_mp3_source_ingest_preserves_source_metadata_in_live_runtime_result() -> None:
    envelope = build_mp3_source_ingest(
        FIXTURE_MP3,
        target_sample_rate_hz=22050,
        chunk_duration_s=0.5,
    )
    payload = build_live_runtime_result(
        envelope,
        chunk_duration_s=0.5,
        target_sample_rate_hz=22050,
        max_queue_depth=64,
    ).to_dict()

    _validate_payload(payload)

    assert payload["source"] == {"kind": "mp3", "reference": str(FIXTURE_MP3)}
    assert payload["input"] == str(FIXTURE_MP3)
    assert payload["status"] == "ok"
    assert payload["error_stage"] is None
    assert payload["error_message"] is None
    assert sorted(payload["stem_paths"].keys()) == ["bass", "drums", "other", "vocals"]


def test_video_audio_source_ingest_preserves_container_metadata_in_live_runtime_result() -> None:
    envelope = build_video_source_ingest(
        FIXTURE_VIDEO,
        target_sample_rate_hz=22050,
        chunk_duration_s=0.5,
    )
    payload = build_live_runtime_result(
        envelope,
        chunk_duration_s=0.5,
        target_sample_rate_hz=22050,
        max_queue_depth=64,
    ).to_dict()

    _validate_payload(payload)

    assert payload["source"]["kind"] == "video_audio"
    assert payload["source"]["reference"] == str(FIXTURE_VIDEO)
    assert payload["source"]["metadata"] == {"container": "mp4"}
    assert payload["input"] == str(FIXTURE_VIDEO)
    assert payload["status"] == "ok"
    assert payload["metadata"]["clock_source"] == "ingest"


def test_mic_source_ingest_with_fake_backend_preserves_source_metadata_in_live_runtime_result() -> None:
    envelope = build_mic_source_ingest(
        "fixture:mic-demo",
        backend=FakeMicCaptureBackend(),
        target_sample_rate_hz=22050,
        chunk_duration_s=0.5,
        capture_duration_s=1.0,
        max_queue_depth=64,
    )
    payload = build_live_runtime_result(
        envelope,
        chunk_duration_s=0.5,
        target_sample_rate_hz=22050,
        max_queue_depth=64,
    ).to_dict()

    _validate_payload(payload)

    assert payload["source"]["kind"] == "mic"
    assert payload["source"]["reference"] == "fixture:mic-demo"
    assert payload["source"]["metadata"] == {
        "backend": "fake",
        "device": "fixture:mic-demo",
        "capture_duration_s": 1.0,
        "sample_rate_hz": 22050,
    }
    assert payload["input"] == "fixture:mic-demo"
    assert payload["status"] == "ok"
    assert payload["metadata"]["mode"] == "smoke"


def test_video_audio_ingest_rejects_corrupt_video_media(tmp_path: Path) -> None:
    corrupt_video = tmp_path / "corrupt.mp4"
    corrupt_video.write_bytes(b"not a video")

    with pytest.raises(DecodeFailedError) as exc_info:
        build_video_source_ingest(
            corrupt_video,
            target_sample_rate_hz=22050,
            chunk_duration_s=0.5,
        )

    assert str(corrupt_video) in str(exc_info.value)


def test_parse_args_rejects_bad_source_mode_argument() -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["--source-mode", "bogus"])

    assert exc_info.value.code == 2
