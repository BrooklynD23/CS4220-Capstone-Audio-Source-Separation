from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Protocol

from .contracts import SourceDescriptor
from .mp3_ingest import DecodeFailedError, build_decoded_audio_from_pcm
from .source_ingest import SourceIngestEnvelope

DEFAULT_MIC_KIND = "mic"
DEFAULT_MIC_BACKEND = "sounddevice"
DEFAULT_MIC_CAPTURE_DURATION_S = 1.0


@dataclass(frozen=True)
class MicCaptureError(RuntimeError):
    """Base error for microphone capture failures surfaced in runtime telemetry."""

    error_stage: str
    device_reference: str
    backend_name: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class MicCaptureFailedError(MicCaptureError):
    """Raised when the capture backend rejects or cannot open the requested device."""


@dataclass(frozen=True)
class MicCaptureTimeoutError(MicCaptureError):
    """Raised when microphone capture exceeds the allowed capture timeout."""


@dataclass(frozen=True)
class CapturedMicAudio:
    """Raw PCM bytes returned from a capture backend."""

    pcm: bytes
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    backend_name: str
    device_reference: str
    capture_duration_s: float


class MicCaptureBackend(Protocol):
    """Backend interface for capturing a short PCM buffer from a microphone device."""

    backend_name: str

    def capture(
        self,
        device_reference: str,
        *,
        sample_rate_hz: int,
        capture_duration_s: float,
        capture_timeout_s: float,
    ) -> CapturedMicAudio:
        ...


@dataclass(frozen=True)
class FakeMicCaptureBackend:
    """Deterministic capture backend used by tests and CI."""

    backend_name: str = "fake"
    tone_hz: float = 440.0

    def capture(
        self,
        device_reference: str,
        *,
        sample_rate_hz: int,
        capture_duration_s: float,
        capture_timeout_s: float,
    ) -> CapturedMicAudio:
        del capture_timeout_s
        frame_count = max(1, int(round(sample_rate_hz * capture_duration_s)))
        pcm = b"\x00\x00" * frame_count
        return CapturedMicAudio(
            pcm=pcm,
            sample_rate_hz=sample_rate_hz,
            channels=1,
            sample_width_bytes=2,
            backend_name=self.backend_name,
            device_reference=device_reference,
            capture_duration_s=capture_duration_s,
        )


class SoundDeviceMicCaptureBackend:
    """Capture PCM from a real microphone via the sounddevice backend when installed."""

    backend_name = DEFAULT_MIC_BACKEND

    def capture(
        self,
        device_reference: str,
        *,
        sample_rate_hz: int,
        capture_duration_s: float,
        capture_timeout_s: float,
    ) -> CapturedMicAudio:
        if sample_rate_hz <= 0:
            raise MicCaptureFailedError(
                error_stage="capture_failed",
                device_reference=device_reference,
                backend_name=self.backend_name,
                message="capture_failed: sample_rate_hz must be greater than zero",
            )
        if capture_duration_s <= 0:
            raise MicCaptureFailedError(
                error_stage="capture_failed",
                device_reference=device_reference,
                backend_name=self.backend_name,
                message="capture_failed: capture_duration_s must be greater than zero",
            )

        try:
            import sounddevice as sd
        except ImportError as exc:  # pragma: no cover - depends on optional runtime extra
            raise MicCaptureFailedError(
                error_stage="capture_failed",
                device_reference=device_reference,
                backend_name=self.backend_name,
                message=(
                    "capture_failed: sounddevice backend is unavailable; install the 'mic' "
                    "extra to capture from a real device"
                ),
            ) from exc

        result: dict[str, bytes | int | float] = {}
        error: dict[str, BaseException] = {}
        frames = max(1, int(round(sample_rate_hz * capture_duration_s)))
        device = None if device_reference in {"", "default"} else device_reference

        def _capture() -> None:
            try:
                recording = sd.rec(
                    frames,
                    samplerate=sample_rate_hz,
                    channels=1,
                    dtype="int16",
                    device=device,
                )
                sd.wait()
                result["pcm"] = recording.tobytes()
                result["sample_rate_hz"] = sample_rate_hz
                result["channels"] = 1
                result["sample_width_bytes"] = 2
            except BaseException as exc:  # pragma: no cover - exercised only on real hardware
                error["exc"] = exc

        worker = threading.Thread(target=_capture, daemon=True)
        worker.start()
        worker.join(capture_timeout_s)
        if worker.is_alive():
            try:
                sd.stop()
            except Exception:
                pass
            raise MicCaptureTimeoutError(
                error_stage="capture_timeout",
                device_reference=device_reference,
                backend_name=self.backend_name,
                message=(
                    f"capture_timeout for {device_reference}: sounddevice exceeded "
                    f"{capture_timeout_s:.3f}s"
                ),
            )
        if "exc" in error:
            raise MicCaptureFailedError(
                error_stage="capture_failed",
                device_reference=device_reference,
                backend_name=self.backend_name,
                message=f"capture_failed for {device_reference}: {error['exc']}",
            ) from error["exc"]

        pcm = bytes(result.get("pcm", b""))
        if not pcm:
            raise MicCaptureFailedError(
                error_stage="capture_failed",
                device_reference=device_reference,
                backend_name=self.backend_name,
                message=f"capture_failed for {device_reference}: capture returned no audio",
            )

        return CapturedMicAudio(
            pcm=pcm,
            sample_rate_hz=int(result.get("sample_rate_hz", sample_rate_hz)),
            channels=int(result.get("channels", 1)),
            sample_width_bytes=int(result.get("sample_width_bytes", 2)),
            backend_name=self.backend_name,
            device_reference=device_reference,
            capture_duration_s=capture_duration_s,
        )


def build_mic_source_descriptor(
    device_reference: str,
    *,
    backend_name: str,
    capture_duration_s: float,
    sample_rate_hz: int,
) -> SourceDescriptor:
    """Create the source descriptor for a microphone capture."""

    return SourceDescriptor(
        kind=DEFAULT_MIC_KIND,
        reference=device_reference,
        metadata={
            "backend": backend_name,
            "device": device_reference,
            "capture_duration_s": capture_duration_s,
            "sample_rate_hz": sample_rate_hz,
        },
    )


def build_mic_source_ingest(
    device_reference: str,
    *,
    backend: MicCaptureBackend | None = None,
    target_sample_rate_hz: int = 44100,
    chunk_duration_s: float = 1.0,
    capture_duration_s: float = DEFAULT_MIC_CAPTURE_DURATION_S,
    capture_timeout_s: float = 30.0,
    max_queue_depth: int | None = None,
) -> SourceIngestEnvelope:
    """Capture microphone PCM and convert it into the shared ingest envelope."""

    capture_backend = backend or SoundDeviceMicCaptureBackend()
    started = time.perf_counter()
    captured = capture_backend.capture(
        device_reference,
        sample_rate_hz=target_sample_rate_hz,
        capture_duration_s=capture_duration_s,
        capture_timeout_s=capture_timeout_s,
    )

    if captured.channels != 1 or captured.sample_width_bytes != 2:
        raise MicCaptureFailedError(
            error_stage="capture_failed",
            device_reference=device_reference,
            backend_name=captured.backend_name,
            message=(
                f"capture_failed for {device_reference}: unsupported capture format "
                f"channels={captured.channels} sample_width_bytes={captured.sample_width_bytes}"
            ),
        )
    if captured.sample_rate_hz != target_sample_rate_hz:
        raise MicCaptureFailedError(
            error_stage="capture_failed",
            device_reference=device_reference,
            backend_name=captured.backend_name,
            message=(
                f"capture_failed for {device_reference}: backend returned sample_rate_hz "
                f"{captured.sample_rate_hz}, expected {target_sample_rate_hz}"
            ),
        )

    source = build_mic_source_descriptor(
        device_reference,
        backend_name=captured.backend_name,
        capture_duration_s=captured.capture_duration_s,
        sample_rate_hz=captured.sample_rate_hz,
    )
    try:
        decoded_audio = build_decoded_audio_from_pcm(
            Path(device_reference),
            captured.pcm,
            target_sample_rate_hz=target_sample_rate_hz,
            chunk_duration_s=chunk_duration_s,
            max_queue_depth=max_queue_depth,
        )
    except DecodeFailedError as exc:
        raise MicCaptureFailedError(
            error_stage="capture_failed",
            device_reference=device_reference,
            backend_name=captured.backend_name,
            message=f"capture_failed for {device_reference}: {exc}",
        ) from exc

    ingest_ms = round((time.perf_counter() - started) * 1000.0, 6)
    return SourceIngestEnvelope(source=source, decoded_audio=decoded_audio, ingest_ms=ingest_ms)


__all__ = [
    "CapturedMicAudio",
    "DEFAULT_MIC_BACKEND",
    "DEFAULT_MIC_CAPTURE_DURATION_S",
    "DEFAULT_MIC_KIND",
    "FakeMicCaptureBackend",
    "MicCaptureBackend",
    "MicCaptureError",
    "MicCaptureFailedError",
    "MicCaptureTimeoutError",
    "SoundDeviceMicCaptureBackend",
    "build_mic_source_descriptor",
    "build_mic_source_ingest",
]
