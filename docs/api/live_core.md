# live_core

**File:** `live_runtime/live_core.py`

Provides model path resolution and the primary function for assembling the `LiveRuntimeResult` artifact from a pre-decoded source envelope. This is the orchestration entry point — callers decode their source using one of the ingest modules and then pass the `SourceIngestEnvelope` here to produce the final result.

---

## Constants

| Name | Type | Value | Description |
|------|------|-------|-------------|
| `DEFAULT_MODEL_PATH` | `str` | `"artifacts/models/umx-live.pt"` | Default UMX model path |
| `DEMUCS_MODEL_PATH` | `str` | `"artifacts/models/demucs-live.pt"` | Demucs model path |
| `SUPPORTED_MODEL_PATHS` | `frozenset[str]` | `{DEFAULT_MODEL_PATH, DEMUCS_MODEL_PATH}` | Set of all first-class supported model paths |
| `DEFAULT_VOCALS_PATH` | `str` | `"artifacts/live/smoke/vocals.wav"` | Fallback vocals stem path |
| `DEFAULT_DRUMS_PATH` | `str` | `"artifacts/live/smoke/drums.wav"` | Fallback drums stem path |
| `DEFAULT_BASS_PATH` | `str` | `"artifacts/live/smoke/bass.wav"` | Fallback bass stem path |
| `DEFAULT_OTHER_PATH` | `str` | `"artifacts/live/smoke/other.wav"` | Fallback other stem path |
| `MAX_SUPPORTED_CHUNK_DURATION_S` | `float` | `30.0` | Maximum allowed chunk duration in seconds |

---

## Dataclasses

### `ModelPathResolution`

Describes how the live runtime resolved the requested model path.

```python
@dataclass(frozen=True)
class ModelPathResolution:
    requested_model_path: str
    model_path: str
    fallback_applied: bool
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `requested_model_path` | `str` | Model path as supplied by the caller |
| `model_path` | `str` | Effective model path after resolution (may equal requested) |
| `fallback_applied` | `bool` | `True` when the requested path was unsupported and `DEFAULT_MODEL_PATH` was substituted |

---

## Functions

### `is_supported_live_model_path`

```python
def is_supported_live_model_path(model_path: str) -> bool
```

Return whether the live runtime can serve the requested model path without applying a fallback.

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `model_path` | `str` | Model path to check (leading/trailing whitespace is stripped) |

#### Returns

`bool` — `True` if `model_path` is in `SUPPORTED_MODEL_PATHS`.

#### Example

```python
from live_runtime.live_core import is_supported_live_model_path

is_supported_live_model_path("artifacts/models/umx-live.pt")    # True
is_supported_live_model_path("artifacts/models/demucs-live.pt") # True
is_supported_live_model_path("artifacts/models/other.pt")       # False
```

---

### `resolve_live_model_path`

```python
def resolve_live_model_path(requested_model_path: str) -> ModelPathResolution
```

Resolve a requested path to the stable live model path, substituting the default when the request is unsupported.

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `requested_model_path` | `str` | Requested model path (leading/trailing whitespace is stripped) |

#### Returns

[`ModelPathResolution`](#modelPathResolution) — contains the original request, the effective path, and whether a fallback was applied.

#### Raises

| Exception | Condition |
|-----------|-----------|
| `ValueError` | `requested_model_path` is empty after stripping |

#### Behavior

- If the requested path is in `SUPPORTED_MODEL_PATHS`, returns it unchanged with `fallback_applied=False`.
- Otherwise, returns `DEFAULT_MODEL_PATH` with `fallback_applied=True`.

#### Example

```python
from live_runtime.live_core import resolve_live_model_path

res = resolve_live_model_path("artifacts/models/umx-live.pt")
# ModelPathResolution(requested_model_path="artifacts/models/umx-live.pt",
#                     model_path="artifacts/models/umx-live.pt",
#                     fallback_applied=False)

res = resolve_live_model_path("artifacts/models/unsupported.pt")
# ModelPathResolution(requested_model_path="artifacts/models/unsupported.pt",
#                     model_path="artifacts/models/umx-live.pt",
#                     fallback_applied=True)
```

---

### `build_live_runtime_result`

```python
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
    stage_timings_override: StageTimings | None = None,
) -> LiveRuntimeResult
```

Compose the complete `LiveRuntimeResult` artifact from a pre-decoded source envelope. This is the main orchestration function for the live runtime pipeline.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source_ingest` | `SourceIngestEnvelope` | — | Pre-decoded source envelope from any ingest module |
| `chunk_duration_s` | `float` | — | Target chunk duration in seconds (keyword-only, required) |
| `target_sample_rate_hz` | `int` | `22050` | Target sample rate; kept for caller compatibility |
| `max_queue_depth` | `int \| None` | `None` | Maximum chunk queue depth; kept for caller compatibility |
| `decode_timeout_s` | `float` | `30.0` | Decode timeout; kept for caller compatibility |
| `device_requested` | `str` | `"cpu"` | Device requested by the caller |
| `device_used` | `str` | `"cpu"` | Device actually used for inference |
| `mode` | `str` | `"smoke"` | Run mode: `"smoke"` or `"full"` |
| `model_path` | `str` | `DEFAULT_MODEL_PATH` | Requested model path (subject to fallback resolution) |
| `stem_routing` | `StemRouting \| None` | `None` | Explicit stem output paths; defaults to smoke paths if `None` |
| `infer_ms_override` | `float \| None` | `None` | When `stage_timings_override` is omitted, supplies `infer_ms` for smoke-style artifacts |
| `stage_timings_override` | `StageTimings \| None` | `None` | Full measured `stft_ms` / `infer_ms` / `istft_ms` / `total_ms` (e.g. Open-Unmix full runs) |

#### Returns

[`LiveRuntimeResult`](contracts.md#liveruntimeresult) — the fully assembled result artifact.

#### Raises

| Exception | Condition |
|-----------|-----------|
| `ValueError` | `chunk_duration_s` is ≤ 0 or > `MAX_SUPPORTED_CHUNK_DURATION_S` (30 s) |
| `ValueError` | The decoded source contained no chunks |

#### Health State Logic

The returned `HealthTelemetry` is set according to these rules (in priority order):

1. `fallback_applied=True` → `health_state="fallback"`
2. `drop_count > 0` → `health_state="degraded"`
3. Otherwise → `health_state="healthy"`

#### Stage Timing Assignment

If `stage_timings_override` is set, those values are written to the artifact unchanged.

Otherwise (smoke-style):

| `StageTimings` field | Source |
|----------------------|--------|
| `stft_ms` | `source_ingest.ingest_ms` (wall-clock time of the ingest call) |
| `infer_ms` | `infer_ms_override` if provided, else a small chunk telemetry stub |
| `istft_ms` | Wall-clock time of the metadata assembly |
| `total_ms` | Sum of the three fields above |

#### Example

```python
from live_runtime.source_ingest import build_mp3_source_ingest
from live_runtime.stem_router import write_live_stems
from live_runtime.live_core import build_live_runtime_result
import json

ingest = build_mp3_source_ingest("track.mp3", chunk_duration_s=1.0)
routing = write_live_stems(ingest, "artifacts/live/run-001/")

result = build_live_runtime_result(
    ingest,
    chunk_duration_s=1.0,
    model_path="artifacts/models/umx-live.pt",
    stem_routing=routing,
)
print(json.dumps(result.to_dict(), indent=2))
```
