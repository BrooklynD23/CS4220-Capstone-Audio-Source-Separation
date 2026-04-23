from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable

from .contracts import SourceDescriptor
from .mp3_ingest import DecodedAudio, decode_mp3_to_pcm

DEFAULT_MP3_KIND = "mp3"


@dataclass(frozen=True)
class SourceIngestEnvelope:
    """Carry a validated source descriptor together with its decoded audio."""

    source: SourceDescriptor
    decoded_audio: DecodedAudio
    ingest_ms: float


def build_mp3_source_descriptor(source_path: Path | str) -> SourceDescriptor:
    """Create the source descriptor used by the current file-backed MP3 path."""

    return SourceDescriptor(kind=DEFAULT_MP3_KIND, reference=str(Path(source_path)))


def build_source_ingest(
    source: SourceDescriptor,
    *,
    decode_audio: Callable[..., DecodedAudio],
    target_sample_rate_hz: int = 44100,
    chunk_duration_s: float = 1.0,
    decode_timeout_s: float = 30.0,
    max_queue_depth: int | None = None,
) -> SourceIngestEnvelope:
    """Decode a validated source into the shared ingest envelope."""

    started = time.perf_counter()
    decoded_audio = decode_audio(
        source.reference,
        target_sample_rate_hz=target_sample_rate_hz,
        chunk_duration_s=chunk_duration_s,
        decode_timeout_s=decode_timeout_s,
        max_queue_depth=max_queue_depth,
    )
    ingest_ms = round((time.perf_counter() - started) * 1000.0, 6)
    return SourceIngestEnvelope(source=source, decoded_audio=decoded_audio, ingest_ms=ingest_ms)


def build_mp3_source_ingest(
    source_path: Path | str,
    *,
    target_sample_rate_hz: int = 44100,
    chunk_duration_s: float = 1.0,
    decode_timeout_s: float = 30.0,
    max_queue_depth: int | None = None,
) -> SourceIngestEnvelope:
    """Decode a file-backed MP3 source into the shared ingest envelope."""

    source = build_mp3_source_descriptor(source_path)
    return build_source_ingest(
        source,
        decode_audio=decode_mp3_to_pcm,
        target_sample_rate_hz=target_sample_rate_hz,
        chunk_duration_s=chunk_duration_s,
        decode_timeout_s=decode_timeout_s,
        max_queue_depth=max_queue_depth,
    )


__all__ = [
    "DEFAULT_MP3_KIND",
    "SourceIngestEnvelope",
    "build_mp3_source_descriptor",
    "build_mp3_source_ingest",
    "build_source_ingest",
]
