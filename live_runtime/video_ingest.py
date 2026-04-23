from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .contracts import SourceDescriptor
from .mp3_ingest import decode_audio_to_pcm
from .source_ingest import SourceIngestEnvelope, build_source_ingest

DEFAULT_VIDEO_KIND = "video_audio"


@dataclass(frozen=True)
class VideoSourceConfig:
    """Capture the file-backed video source metadata used by the CLI."""

    reference: str
    container: str


def build_video_source_descriptor(source_path: Path | str) -> SourceDescriptor:
    """Create the source descriptor for a video container with an audio track."""

    path = Path(source_path)
    container = path.suffix.lstrip(".").lower() or "mp4"
    return SourceDescriptor(
        kind=DEFAULT_VIDEO_KIND,
        reference=str(path),
        metadata={"container": container},
    )


def build_video_source_ingest(
    source_path: Path | str,
    *,
    target_sample_rate_hz: int = 44100,
    chunk_duration_s: float = 1.0,
    decode_timeout_s: float = 30.0,
    max_queue_depth: int | None = None,
) -> SourceIngestEnvelope:
    """Decode audio from a video container into the shared ingest envelope."""

    source = build_video_source_descriptor(source_path)
    return build_source_ingest(
        source,
        decode_audio=decode_audio_to_pcm,
        target_sample_rate_hz=target_sample_rate_hz,
        chunk_duration_s=chunk_duration_s,
        decode_timeout_s=decode_timeout_s,
        max_queue_depth=max_queue_depth,
    )


__all__ = [
    "DEFAULT_VIDEO_KIND",
    "VideoSourceConfig",
    "build_video_source_descriptor",
    "build_video_source_ingest",
]
