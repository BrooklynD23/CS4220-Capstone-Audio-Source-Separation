from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path("artifacts/schema/live_runtime_result.schema.json")

LiveMode = Literal["smoke", "full"]
RuntimeStatus = Literal["ok", "error"]
RuntimeDevice = Literal["cpu", "gpu"]
RuntimeStage = Literal["stft", "infer", "istft"]
HealthState = Literal["healthy", "degraded", "fallback"]
SourceKind = Literal["mp3", "video_audio", "mic"]


@dataclass(frozen=True)
class SourceDescriptor:
    """Describe the high-level source without assuming it is a file path."""

    kind: SourceKind
    reference: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = str(self.kind).strip()
        reference = str(self.reference).strip()
        metadata = dict(self.metadata)

        if not kind:
            raise ValueError("source kind must be non-empty")
        if kind not in ("mp3", "video_audio", "mic"):
            raise ValueError(f"unsupported source kind: {kind}")
        if not reference:
            raise ValueError("source reference must be non-empty")
        if kind in {"video_audio", "mic"} and not metadata:
            raise ValueError(f"{kind} source requires metadata")

        object.__setattr__(self, "kind", kind)  # type: ignore[misc]
        object.__setattr__(self, "reference", reference)  # type: ignore[misc]
        object.__setattr__(self, "metadata", metadata)  # type: ignore[misc]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "reference": self.reference,
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class ChunkInput:
    """Describe one processed live chunk."""

    input: str
    sample_rate_hz: int
    chunk_duration_s: float
    chunk_index: int


@dataclass(frozen=True)
class StageTimings:
    """Record the preserved S01 stage timing fields."""

    stft_ms: float
    infer_ms: float
    istft_ms: float
    total_ms: float


@dataclass(frozen=True)
class StemRouting:
    """Describe the exact four stem outputs emitted by the live path."""

    vocals_path: str
    drums_path: str
    bass_path: str
    other_path: str


@dataclass(frozen=True)
class FailureStateTelemetry:
    """Capture the runtime failure visibility contract."""

    status: RuntimeStatus
    error_stage: str | None
    error_message: str | None
    timestamp: str


@dataclass(frozen=True)
class HealthTelemetry:
    """Capture the runtime health and fallback contract."""

    health_state: HealthState
    health_reason: str
    requested_model_path: str
    fallback_applied: bool

    def __post_init__(self) -> None:
        health_state = str(self.health_state).strip()
        health_reason = str(self.health_reason).strip()
        requested_model_path = str(self.requested_model_path).strip()

        if health_state not in ("healthy", "degraded", "fallback"):
            raise ValueError(f"unsupported health state: {health_state}")
        if not health_reason:
            raise ValueError("health reason must be non-empty")
        if not requested_model_path:
            raise ValueError("requested model path must be non-empty")

        object.__setattr__(self, "health_state", health_state)  # type: ignore[misc]
        object.__setattr__(self, "health_reason", health_reason)  # type: ignore[misc]
        object.__setattr__(self, "requested_model_path", requested_model_path)  # type: ignore[misc]


@dataclass(frozen=True)
class LiveRuntimeMetadata:
    """Capture the live-only telemetry exposed by the runtime."""

    device_requested: RuntimeDevice
    device_used: RuntimeDevice
    mode: LiveMode
    clock_source: str
    clock_fallback: bool
    samples_processed: int
    channels: int
    sample_width_bytes: int
    stages: tuple[RuntimeStage, ...]
    queue_depth: int
    drop_count: int
    model_path: str


@dataclass(frozen=True)
class LiveRuntimeResult:
    """Typed representation of the live runtime artifact."""

    source: SourceDescriptor
    chunk_input: ChunkInput
    stage_timings: StageTimings
    stem_routing: StemRouting
    failure_state: FailureStateTelemetry
    health: HealthTelemetry
    telemetry: LiveRuntimeMetadata

    def to_dict(self) -> dict[str, Any]:
        """Flatten the runtime result into the JSON artifact shape."""

        payload: dict[str, Any] = {
            "source": self.source.to_dict(),
            **asdict(self.chunk_input),
            **asdict(self.stage_timings),
            **asdict(self.failure_state),
            **asdict(self.health),
            "queue_depth": self.telemetry.queue_depth,
            "drop_count": self.telemetry.drop_count,
            "model_path": self.telemetry.model_path,
            "stem_paths": {
                "vocals": self.stem_routing.vocals_path,
                "drums": self.stem_routing.drums_path,
                "bass": self.stem_routing.bass_path,
                "other": self.stem_routing.other_path,
            },
            "metadata": {
                "device_requested": self.telemetry.device_requested,
                "device_used": self.telemetry.device_used,
                "mode": self.telemetry.mode,
                "clock_source": self.telemetry.clock_source,
                "clock_fallback": self.telemetry.clock_fallback,
                "samples_processed": self.telemetry.samples_processed,
                "channels": self.telemetry.channels,
                "sample_width_bytes": self.telemetry.sample_width_bytes,
                "stages": list(self.telemetry.stages),
            },
        }
        return payload


def load_live_runtime_schema(schema_path: Path | str = SCHEMA_PATH) -> dict[str, Any]:
    """Load the live runtime schema and fail closed on missing or invalid files."""

    schema_file = Path(schema_path)
    if not schema_file.exists():
        raise FileNotFoundError(f"Live runtime schema not found: {schema_file}")

    with schema_file.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)

    if not isinstance(schema, dict) or not schema:
        raise ValueError(f"Live runtime schema must be a non-empty JSON object: {schema_file}")

    return schema


def validate_live_runtime_result(
    payload: dict[str, Any],
    schema: dict[str, Any] | None = None,
    schema_path: Path | str = SCHEMA_PATH,
) -> dict[str, Any]:
    """Validate a live runtime artifact against the live contract schema."""

    active_schema = schema if schema is not None else load_live_runtime_schema(schema_path)
    Draft202012Validator(active_schema).validate(payload)
    return payload
