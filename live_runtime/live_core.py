from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import time

from .contracts import (
    ChunkInput,
    FailureStateTelemetry,
    HealthTelemetry,
    LiveRuntimeMetadata,
    LiveRuntimeResult,
    StageTimings,
    StemRouting,
)
from .source_ingest import SourceIngestEnvelope


DEFAULT_MODEL_PATH = "artifacts/models/umx-live.pt"
DEMUCS_MODEL_PATH = "artifacts/models/demucs-live.pt"
SUPPORTED_MODEL_PATHS = frozenset({DEFAULT_MODEL_PATH, DEMUCS_MODEL_PATH})
DEFAULT_VOCALS_PATH = "artifacts/live/smoke/vocals.wav"
DEFAULT_DRUMS_PATH = "artifacts/live/smoke/drums.wav"
DEFAULT_BASS_PATH = "artifacts/live/smoke/bass.wav"
DEFAULT_OTHER_PATH = "artifacts/live/smoke/other.wav"
MAX_SUPPORTED_CHUNK_DURATION_S = 30.0
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPathResolution:
    """Describe how the live runtime resolves the requested model path."""

    requested_model_path: str
    model_path: str
    fallback_applied: bool


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _validate_chunk_duration(chunk_duration_s: float) -> None:
    if chunk_duration_s <= 0:
        raise ValueError("chunk_duration_s must be greater than 0")
    if chunk_duration_s > MAX_SUPPORTED_CHUNK_DURATION_S:
        raise ValueError(
            f"chunk_duration_s must not exceed {MAX_SUPPORTED_CHUNK_DURATION_S} seconds"
        )


def is_supported_live_model_path(model_path: str) -> bool:
    """Return whether the live runtime can serve the requested model path."""

    requested = str(model_path).strip()
    return requested in SUPPORTED_MODEL_PATHS


def resolve_live_model_path(requested_model_path: str) -> ModelPathResolution:
    """Resolve a requested path to the stable live model path when needed."""

    requested = str(requested_model_path).strip()
    if not requested:
        raise ValueError("model_path must be non-empty")

    if is_supported_live_model_path(requested):
        return ModelPathResolution(
            requested_model_path=requested,
            model_path=requested,
            fallback_applied=False,
        )

    return ModelPathResolution(
        requested_model_path=requested,
        model_path=DEFAULT_MODEL_PATH,
        fallback_applied=True,
    )


def _build_failure_state(
    *,
    status: str,
    error_stage: str | None,
    error_message: str | None,
) -> FailureStateTelemetry:
    return FailureStateTelemetry(
        status=status,  # type: ignore[arg-type]
        error_stage=error_stage,
        error_message=error_message,
        timestamp=_now_iso(),
    )


def _build_health_telemetry(
    *,
    error_stage: str | None,
    error_message: str | None,
    requested_model_path: str,
    model_path: str,
    fallback_applied: bool,
    queue_depth: int,
    drop_count: int,
) -> HealthTelemetry:
    if fallback_applied:
        health_state = "fallback"
        health_reason = (
            error_message
            or f"requested model path {requested_model_path} fell back to {model_path}"
        )
    elif drop_count > 0:
        health_state = "degraded"
        health_reason = (
            error_message
            or f"backpressure degraded after {queue_depth} queued chunks; dropped {drop_count} additional chunks"
        )
    else:
        health_state = "healthy"
        health_reason = "runtime operating normally"

    if error_stage and error_message and not fallback_applied and drop_count == 0:
        health_reason = error_message

    return HealthTelemetry(
        health_state=health_state,
        health_reason=health_reason,
        requested_model_path=requested_model_path,
        fallback_applied=fallback_applied,
    )


def build_live_runtime_result(
    source_ingest: SourceIngestEnvelope,
    *,
    chunk_duration_s: float,
    target_sample_rate_hz: int = 22050,
    max_queue_depth: int | None = None,
    decode_timeout_s: float = 30.0,
    device_requested: str = "cpu",
    device_used: str = "cpu",
    mode: str = "smoke",
    model_path: str = DEFAULT_MODEL_PATH,
    stem_routing: StemRouting | None = None,
    infer_ms_override: float | None = None,
) -> LiveRuntimeResult:
    """Compose the live runtime artifact from a pre-decoded source envelope.

    Pass infer_ms_override to record real GPU inference time instead of the
    default near-zero stub timings.
    """

    _validate_chunk_duration(chunk_duration_s)
    _ = target_sample_rate_hz, decode_timeout_s  # preserved for caller compatibility

    decoded = source_ingest.decoded_audio
    if decoded.chunk_count == 0:
        raise ValueError(f"decoded source contained no chunks: {decoded.source_path}")

    model_resolution = resolve_live_model_path(model_path)

    chunk_started = time.perf_counter()
    last_chunk = decoded.chunks[-1]
    queue_depth = last_chunk.queue_depth
    drop_count = last_chunk.drop_count

    chunk_ms = round((time.perf_counter() - chunk_started) * 1000.0, 6)
    telemetry_started = time.perf_counter()
    telemetry_ms = round((time.perf_counter() - telemetry_started) * 1000.0, 6)

    if stem_routing is None:
        stem_routing = StemRouting(
            vocals_path=DEFAULT_VOCALS_PATH,
            drums_path=DEFAULT_DRUMS_PATH,
            bass_path=DEFAULT_BASS_PATH,
            other_path=DEFAULT_OTHER_PATH,
        )

    effective_infer_ms = infer_ms_override if infer_ms_override is not None else chunk_ms
    effective_total_ms = round(source_ingest.ingest_ms + effective_infer_ms + telemetry_ms, 6)

    _log.info("live separation start source=%s mode=%s", source_ingest.source.reference, mode)
    health = _build_health_telemetry(
        error_stage=None,
        error_message=None,
        requested_model_path=model_resolution.requested_model_path,
        model_path=model_resolution.model_path,
        fallback_applied=model_resolution.fallback_applied,
        queue_depth=queue_depth,
        drop_count=drop_count,
    )
    if health.health_state in {"degraded", "fallback"}:
        _log.warning("live runtime health %s: %s", health.health_state, health.health_reason)

    result = LiveRuntimeResult(
        source=source_ingest.source,
        chunk_input=ChunkInput(
            input=source_ingest.source.reference,
            sample_rate_hz=decoded.sample_rate_hz,
            chunk_duration_s=decoded.chunk_duration_s,
            chunk_index=last_chunk.chunk_index,
        ),
        stage_timings=StageTimings(
            stft_ms=source_ingest.ingest_ms,
            infer_ms=effective_infer_ms,
            istft_ms=telemetry_ms,
            total_ms=effective_total_ms,
        ),
        stem_routing=stem_routing,
        failure_state=_build_failure_state(
            status="ok",
            error_stage=None,
            error_message=None,
        ),
        health=health,
        telemetry=LiveRuntimeMetadata(
            device_requested=device_requested,  # type: ignore[arg-type]
            device_used=device_used,  # type: ignore[arg-type]
            mode=mode,  # type: ignore[arg-type]
            clock_source="ingest",
            clock_fallback=False,
            samples_processed=decoded.total_frames,
            channels=decoded.channels,
            sample_width_bytes=decoded.sample_width_bytes,
            stages=("stft", "infer", "istft"),
            queue_depth=queue_depth,
            drop_count=drop_count,
            model_path=model_resolution.model_path,
        ),
    )
    _log.info(
        "live separation complete source=%s total_ms=%.6f",
        source_ingest.source.reference,
        effective_total_ms,
    )
    return result
