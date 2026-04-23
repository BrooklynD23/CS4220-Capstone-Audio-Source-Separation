# contracts

**File:** `live_runtime/contracts.py`

Defines all frozen dataclasses, type aliases, constants, and schema utilities that form the live runtime type system. Every JSON artifact produced by the live runtime is constructed from these types and validated against the schema loaded by this module.

---

## Constants

### `SCHEMA_PATH`

```python
SCHEMA_PATH: Path = Path("artifacts/schema/live_runtime_result.schema.json")
```

Default filesystem path for the live runtime JSON schema. Resolved relative to the process working directory.

---

## Type Aliases

| Alias | Type | Allowed Values |
|-------|------|----------------|
| `LiveMode` | `Literal` | `"smoke"`, `"full"` |
| `RuntimeStatus` | `Literal` | `"ok"`, `"error"` |
| `RuntimeDevice` | `Literal` | `"cpu"`, `"gpu"` |
| `RuntimeStage` | `Literal` | `"stft"`, `"infer"`, `"istft"` |
| `HealthState` | `Literal` | `"healthy"`, `"degraded"`, `"fallback"` |
| `SourceKind` | `Literal` | `"mp3"`, `"video_audio"`, `"mic"` |

---

## Dataclasses

All dataclasses use `@dataclass(frozen=True)` — instances are immutable after construction.

---

### `SourceDescriptor`

Describes the high-level source without assuming it is a file path.

```python
@dataclass(frozen=True)
class SourceDescriptor:
    kind: SourceKind
    reference: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `kind` | `SourceKind` | Source type: `"mp3"`, `"video_audio"`, or `"mic"` |
| `reference` | `str` | Path to the file or device identifier |
| `metadata` | `dict[str, Any]` | Source-specific metadata (required for `"video_audio"` and `"mic"`) |

#### Validation (enforced in `__post_init__`)

- `kind` must be non-empty and one of `"mp3"`, `"video_audio"`, `"mic"`.
- `reference` must be non-empty.
- `"video_audio"` and `"mic"` sources require a non-empty `metadata` dict.

**Raises:** `ValueError` if any validation rule is violated.

#### Methods

##### `to_dict() -> dict[str, Any]`

Serialize to a JSON-compatible dictionary. `metadata` is omitted when empty.

```python
descriptor = SourceDescriptor(kind="mp3", reference="track.mp3")
descriptor.to_dict()
# {"kind": "mp3", "reference": "track.mp3"}
```

---

### `ChunkInput`

Describes one processed live chunk.

```python
@dataclass(frozen=True)
class ChunkInput:
    input: str
    sample_rate_hz: int
    chunk_duration_s: float
    chunk_index: int
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `input` | `str` | Source reference (path or device) |
| `sample_rate_hz` | `int` | Sample rate of the decoded audio in Hz |
| `chunk_duration_s` | `float` | Duration of each chunk in seconds |
| `chunk_index` | `int` | Zero-based index of the last processed chunk |

---

### `StageTimings`

Records the S01 pipeline stage timing fields.

```python
@dataclass(frozen=True)
class StageTimings:
    stft_ms: float
    infer_ms: float
    istft_ms: float
    total_ms: float
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `stft_ms` | `float` | Ingest/STFT stage wall-clock time in milliseconds |
| `infer_ms` | `float` | Inference stage wall-clock time in milliseconds |
| `istft_ms` | `float` | ISTFT/post-processing stage wall-clock time in milliseconds |
| `total_ms` | `float` | Sum of all stage timings |

---

### `StemRouting`

Describes the exact four stem output paths emitted by the live pipeline.

```python
@dataclass(frozen=True)
class StemRouting:
    vocals_path: str
    drums_path: str
    bass_path: str
    other_path: str
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `vocals_path` | `str` | Absolute or relative path to the vocals WAV |
| `drums_path` | `str` | Absolute or relative path to the drums WAV |
| `bass_path` | `str` | Absolute or relative path to the bass WAV |
| `other_path` | `str` | Absolute or relative path to the other WAV |

---

### `FailureStateTelemetry`

Captures the runtime failure visibility contract.

```python
@dataclass(frozen=True)
class FailureStateTelemetry:
    status: RuntimeStatus
    error_stage: str | None
    error_message: str | None
    timestamp: str
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `status` | `RuntimeStatus` | `"ok"` on success, `"error"` on failure |
| `error_stage` | `str \| None` | Pipeline stage where the error occurred, or `None` |
| `error_message` | `str \| None` | Human-readable error detail, or `None` |
| `timestamp` | `str` | ISO-8601 UTC timestamp of result construction |

---

### `HealthTelemetry`

Captures the runtime health and fallback contract.

```python
@dataclass(frozen=True)
class HealthTelemetry:
    health_state: HealthState
    health_reason: str
    requested_model_path: str
    fallback_applied: bool
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `health_state` | `HealthState` | `"healthy"`, `"degraded"` (drop backpressure), or `"fallback"` (unsupported model) |
| `health_reason` | `str` | Human-readable explanation of the current health state |
| `requested_model_path` | `str` | Model path as originally requested |
| `fallback_applied` | `bool` | `True` if the requested model was unsupported and default was used |

#### Validation (enforced in `__post_init__`)

- `health_state` must be one of `"healthy"`, `"degraded"`, `"fallback"`.
- `health_reason` must be non-empty.
- `requested_model_path` must be non-empty.

**Raises:** `ValueError` if any validation rule is violated.

---

### `LiveRuntimeMetadata`

Captures the live-only telemetry exposed by the runtime.

```python
@dataclass(frozen=True)
class LiveRuntimeMetadata:
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
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `device_requested` | `RuntimeDevice` | Device requested by the caller (`"cpu"` or `"gpu"`) |
| `device_used` | `RuntimeDevice` | Device actually used during inference |
| `mode` | `LiveMode` | Run mode: `"smoke"` or `"full"` |
| `clock_source` | `str` | Source of the timing clock (e.g. `"ingest"`) |
| `clock_fallback` | `bool` | Whether the timing clock fell back to a secondary source |
| `samples_processed` | `int` | Total PCM frames decoded |
| `channels` | `int` | Number of audio channels (always `1` — mono) |
| `sample_width_bytes` | `int` | Bytes per sample (always `2` — int16) |
| `stages` | `tuple[RuntimeStage, ...]` | Ordered pipeline stage names |
| `queue_depth` | `int` | Chunk queue depth at the last processed chunk |
| `drop_count` | `int` | Number of chunks dropped due to backpressure |
| `model_path` | `str` | Effective model path used after fallback resolution |

---

### `LiveRuntimeResult`

Typed representation of the complete live runtime artifact. This is the top-level result object.

```python
@dataclass(frozen=True)
class LiveRuntimeResult:
    source: SourceDescriptor
    chunk_input: ChunkInput
    stage_timings: StageTimings
    stem_routing: StemRouting
    failure_state: FailureStateTelemetry
    health: HealthTelemetry
    telemetry: LiveRuntimeMetadata
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `source` | `SourceDescriptor` | Source description |
| `chunk_input` | `ChunkInput` | Chunk input parameters |
| `stage_timings` | `StageTimings` | Per-stage timing measurements |
| `stem_routing` | `StemRouting` | Output paths for the four WAV stems |
| `failure_state` | `FailureStateTelemetry` | Status and error information |
| `health` | `HealthTelemetry` | Health state and model fallback information |
| `telemetry` | `LiveRuntimeMetadata` | Device, mode, and processing metadata |

#### Methods

##### `to_dict() -> dict[str, Any]`

Flattens the entire result into the JSON artifact shape expected by the schema validator.

```python
result: LiveRuntimeResult = ...
payload = result.to_dict()
# payload is now a flat dict matching live_runtime_result.schema.json
```

---

## Functions

### `load_live_runtime_schema`

```python
def load_live_runtime_schema(
    schema_path: Path | str = SCHEMA_PATH,
) -> dict[str, Any]
```

Load the live runtime JSON schema, failing closed on missing or malformed files.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `schema_path` | `Path \| str` | `SCHEMA_PATH` | Path to the JSON schema file |

#### Returns

`dict[str, Any]` — the parsed schema object.

#### Raises

| Exception | Condition |
|-----------|-----------|
| `FileNotFoundError` | Schema file does not exist at `schema_path` |
| `ValueError` | File exists but is not a non-empty JSON object |

#### Example

```python
from live_runtime.contracts import load_live_runtime_schema

schema = load_live_runtime_schema()
schema = load_live_runtime_schema("path/to/custom_schema.json")
```

---

### `validate_live_runtime_result`

```python
def validate_live_runtime_result(
    payload: dict[str, Any],
    schema: dict[str, Any] | None = None,
    schema_path: Path | str = SCHEMA_PATH,
) -> dict[str, Any]
```

Validate a live runtime artifact dict against the live contract schema using Draft 2020-12.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `payload` | `dict[str, Any]` | — | The artifact dictionary to validate (from `LiveRuntimeResult.to_dict()`) |
| `schema` | `dict[str, Any] \| None` | `None` | Pre-loaded schema; if `None` the schema is loaded from `schema_path` |
| `schema_path` | `Path \| str` | `SCHEMA_PATH` | Path used to load the schema when `schema` is `None` |

#### Returns

`dict[str, Any]` — the original `payload` unchanged (validates in-place and returns for chaining).

#### Raises

| Exception | Condition |
|-----------|-----------|
| `jsonschema.ValidationError` | Payload does not conform to the schema |
| `FileNotFoundError` | Schema file not found and `schema` is `None` |

#### Example

```python
from live_runtime.contracts import validate_live_runtime_result

payload = result.to_dict()
validate_live_runtime_result(payload)  # raises ValidationError if invalid

# Supply a pre-loaded schema to avoid repeated disk reads
schema = load_live_runtime_schema()
validate_live_runtime_result(payload, schema=schema)
```
