from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import site
import subprocess
from typing import Final


DEFAULT_TARGET_SAMPLE_RATE_HZ: Final[int] = 44100
DEFAULT_DECODE_TIMEOUT_S: Final[float] = 30.0


def _resolve_ffmpeg_executable() -> Path:
    """Locate a bundled ffmpeg binary without depending on package import paths."""

    user_site = Path(site.getusersitepackages())
    bundled_dir = user_site / "imageio_ffmpeg" / "binaries"
    if bundled_dir.exists():
        for candidate in sorted(bundled_dir.iterdir()):
            if candidate.name.startswith("ffmpeg-") and candidate.is_file():
                return candidate

    for candidate_name in ("ffmpeg", "ffmpeg.exe"):
        candidate = Path(candidate_name)
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "ffmpeg executable not found; install imageio-ffmpeg or provide ffmpeg on PATH"
    )


@dataclass(frozen=True)
class DecodeError(RuntimeError):
    """Base error for decode failures that should be surfaced in runtime telemetry."""

    error_stage: str
    source_path: Path
    codec_context: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class DecodeFailedError(DecodeError):
    """Raised when ffmpeg rejects the source media."""


@dataclass(frozen=True)
class DecodeTimeoutError(DecodeError):
    """Raised when decode takes too long and must be surfaced as a failure stage."""


@dataclass(frozen=True)
class DecodedChunk:
    """Describe one deterministic PCM chunk produced from the decoded clip."""

    chunk_index: int
    frame_offset: int
    frame_count: int
    queue_depth: int
    drop_count: int
    pcm: bytes


@dataclass(frozen=True)
class DecodedAudio:
    """Decoded PCM and its fixed-duration chunk view."""

    source_path: Path
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    chunk_duration_s: float
    total_frames: int
    pcm: bytes
    chunks: tuple[DecodedChunk, ...]

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


def _normalize_source_path(source_path: Path | str) -> Path:
    path = Path(source_path)
    return path


def _validate_chunk_duration(chunk_duration_s: float) -> None:
    if chunk_duration_s <= 0:
        raise ValueError("chunk_duration_s must be greater than 0")


def _decode_source_pcm_bytes(
    source_path: Path,
    *,
    target_sample_rate_hz: int,
    decode_timeout_s: float,
) -> bytes:
    if not source_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {source_path}")

    ffmpeg_exe = _resolve_ffmpeg_executable()
    command = [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(target_sample_rate_hz),
        "-f",
        "s16le",
        "pipe:1",
    ]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=decode_timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise DecodeTimeoutError(
            error_stage="decode_timeout",
            source_path=source_path,
            codec_context="ffmpeg subprocess timeout",
            message=(
                f"decode_timeout for {source_path}: ffmpeg exceeded {decode_timeout_s:.3f}s"
            ),
        ) from exc

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        if not stderr:
            stderr = "ffmpeg returned a non-zero exit code without stderr output"
        raise DecodeFailedError(
            error_stage="decode_failed",
            source_path=source_path,
            codec_context=stderr,
            message=f"decode_failed for {source_path}: {stderr}",
        )

    return completed.stdout


def _chunk_pcm(
    pcm: bytes,
    *,
    source_path: Path,
    sample_rate_hz: int,
    chunk_duration_s: float,
    max_queue_depth: int | None,
) -> tuple[DecodedChunk, ...]:
    frame_size = 2  # mono s16le
    if len(pcm) % frame_size != 0:
        raise DecodeFailedError(
            error_stage="decode_failed",
            source_path=source_path,
            codec_context="decoded PCM byte length was not aligned to 16-bit frames",
            message=f"decode_failed for {source_path}: decoded PCM was not frame aligned",
        )

    total_frames = len(pcm) // frame_size
    if total_frames <= 0:
        raise DecodeFailedError(
            error_stage="decode_failed",
            source_path=source_path,
            codec_context="decoded PCM contained no frames",
            message=f"decode_failed for {source_path}: decoded PCM contained no frames",
        )

    chunk_frames = int(round(sample_rate_hz * chunk_duration_s))
    if chunk_frames <= 0:
        raise ValueError("chunk_duration_s produced an empty chunk; increase the duration")

    chunks: list[DecodedChunk] = []
    total_chunks = (total_frames + chunk_frames - 1) // chunk_frames
    for chunk_index in range(total_chunks):
        frame_offset = chunk_index * chunk_frames
        frame_count = min(chunk_frames, total_frames - frame_offset)
        start_byte = frame_offset * frame_size
        end_byte = start_byte + frame_count * frame_size
        queue_depth = chunk_index + 1
        if max_queue_depth is not None:
            queue_depth = min(queue_depth, max_queue_depth)
        drop_count = 0
        if max_queue_depth is not None and chunk_index + 1 > max_queue_depth:
            drop_count = (chunk_index + 1) - max_queue_depth

        chunks.append(
            DecodedChunk(
                chunk_index=chunk_index,
                frame_offset=frame_offset,
                frame_count=frame_count,
                queue_depth=queue_depth,
                drop_count=drop_count,
                pcm=pcm[start_byte:end_byte],
            )
        )

    return tuple(chunks)


def build_decoded_audio_from_pcm(
    source_path: Path | str,
    pcm: bytes,
    *,
    target_sample_rate_hz: int = DEFAULT_TARGET_SAMPLE_RATE_HZ,
    chunk_duration_s: float = 1.0,
    max_queue_depth: int | None = None,
) -> DecodedAudio:
    """Build the deterministic decoded audio envelope from already-decoded PCM bytes."""

    _validate_chunk_duration(chunk_duration_s)
    normalized_path = _normalize_source_path(source_path)
    chunks = _chunk_pcm(
        pcm,
        source_path=normalized_path,
        sample_rate_hz=target_sample_rate_hz,
        chunk_duration_s=chunk_duration_s,
        max_queue_depth=max_queue_depth,
    )
    return DecodedAudio(
        source_path=normalized_path,
        sample_rate_hz=target_sample_rate_hz,
        channels=1,
        sample_width_bytes=2,
        chunk_duration_s=chunk_duration_s,
        total_frames=len(pcm) // 2,
        pcm=pcm,
        chunks=chunks,
    )


def decode_audio_to_pcm(
    source_path: Path | str,
    *,
    target_sample_rate_hz: int = DEFAULT_TARGET_SAMPLE_RATE_HZ,
    chunk_duration_s: float = 1.0,
    decode_timeout_s: float = DEFAULT_DECODE_TIMEOUT_S,
    max_queue_depth: int | None = None,
) -> DecodedAudio:
    """Decode any ffmpeg-readable audio source into mono PCM and fixed-duration chunks."""

    normalized_path = _normalize_source_path(source_path)
    pcm = _decode_source_pcm_bytes(
        normalized_path,
        target_sample_rate_hz=target_sample_rate_hz,
        decode_timeout_s=decode_timeout_s,
    )
    return build_decoded_audio_from_pcm(
        normalized_path,
        pcm,
        target_sample_rate_hz=target_sample_rate_hz,
        chunk_duration_s=chunk_duration_s,
        max_queue_depth=max_queue_depth,
    )


def decode_mp3_to_pcm(
    source_path: Path | str,
    *,
    target_sample_rate_hz: int = DEFAULT_TARGET_SAMPLE_RATE_HZ,
    chunk_duration_s: float = 1.0,
    decode_timeout_s: float = DEFAULT_DECODE_TIMEOUT_S,
    max_queue_depth: int | None = None,
) -> DecodedAudio:
    """Decode an MP3 clip into mono PCM and emit deterministic fixed-duration chunks."""

    return decode_audio_to_pcm(
        source_path,
        target_sample_rate_hz=target_sample_rate_hz,
        chunk_duration_s=chunk_duration_s,
        decode_timeout_s=decode_timeout_s,
        max_queue_depth=max_queue_depth,
    )
