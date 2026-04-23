# source_ingest

**File:** `live_runtime/source_ingest.py`

Provides a source-agnostic ingest envelope and convenience helpers for building and decoding MP3 sources. This module defines the shared `SourceIngestEnvelope` type that all ingest paths (MP3, mic, video) must produce. The envelope carries the validated `SourceDescriptor`, the decoded `DecodedAudio`, and the wall-clock ingest time.

---

## Constants

| Name | Type | Value | Description |
|------|------|-------|-------------|
| `DEFAULT_MP3_KIND` | `str` | `"mp3"` | Source kind string for file-backed MP3 sources |

---

## Dataclasses

### `SourceIngestEnvelope`

Carries a validated source descriptor together with its decoded audio and ingest timing.

```python
@dataclass(frozen=True)
class SourceIngestEnvelope:
    source: SourceDescriptor
    decoded_audio: DecodedAudio
    ingest_ms: float
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `source` | `SourceDescriptor` | Validated source descriptor (kind, reference, metadata) |
| `decoded_audio` | `DecodedAudio` | Fully decoded PCM audio with chunk view |
| `ingest_ms` | `float` | Wall-clock time in milliseconds for the decode operation |

---

## Functions

### `build_mp3_source_descriptor`

```python
def build_mp3_source_descriptor(source_path: Path | str) -> SourceDescriptor
```

Create a `SourceDescriptor` for a file-backed MP3 source.

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `source_path` | `Path \| str` | Path to the MP3 file |

#### Returns

[`SourceDescriptor`](contracts.md#sourcedescriptor) with `kind="mp3"` and `reference=str(Path(source_path))`.

#### Example

```python
from live_runtime.source_ingest import build_mp3_source_descriptor

descriptor = build_mp3_source_descriptor("audio/track.mp3")
# SourceDescriptor(kind="mp3", reference="audio/track.mp3", metadata={})
```

---

### `build_source_ingest`

```python
def build_source_ingest(
    source: SourceDescriptor,
    *,
    decode_audio: Callable[..., DecodedAudio],
    target_sample_rate_hz: int = 44100,
    chunk_duration_s: float = 1.0,
    decode_timeout_s: float = 30.0,
    max_queue_depth: int | None = None,
) -> SourceIngestEnvelope
```

Decode a validated source into the shared ingest envelope using the provided decode callable. This is the generic implementation used internally by the source-specific helpers; callers should prefer `build_mp3_source_ingest` or the equivalent video/mic helpers unless implementing a custom source.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `SourceDescriptor` | — | Validated source descriptor |
| `decode_audio` | `Callable[..., DecodedAudio]` | — | Decode function with the `decode_mp3_to_pcm` signature (keyword-only) |
| `target_sample_rate_hz` | `int` | `44100` | Target sample rate for PCM output |
| `chunk_duration_s` | `float` | `1.0` | Duration of each PCM chunk in seconds |
| `decode_timeout_s` | `float` | `30.0` | Maximum decode time before raising a timeout error |
| `max_queue_depth` | `int \| None` | `None` | Cap on chunk queue depth; `None` means unlimited |

#### Returns

[`SourceIngestEnvelope`](#sourceingestenvelope) — the decoded source wrapped in the shared envelope.

#### Raises

Propagates any exception raised by the `decode_audio` callable (e.g. `DecodeFailedError`, `DecodeTimeoutError`).

#### Example

```python
from live_runtime.source_ingest import build_source_ingest, build_mp3_source_descriptor
from live_runtime.mp3_ingest import decode_mp3_to_pcm

source = build_mp3_source_descriptor("track.mp3")
envelope = build_source_ingest(
    source,
    decode_audio=decode_mp3_to_pcm,
    target_sample_rate_hz=44100,
    chunk_duration_s=1.0,
)
```

---

### `build_mp3_source_ingest`

```python
def build_mp3_source_ingest(
    source_path: Path | str,
    *,
    target_sample_rate_hz: int = 44100,
    chunk_duration_s: float = 1.0,
    decode_timeout_s: float = 30.0,
    max_queue_depth: int | None = None,
) -> SourceIngestEnvelope
```

Decode a file-backed MP3 source into the shared ingest envelope. This is the primary convenience function for MP3 sources.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source_path` | `Path \| str` | — | Path to the MP3 file |
| `target_sample_rate_hz` | `int` | `44100` | Target sample rate for PCM output |
| `chunk_duration_s` | `float` | `1.0` | Duration of each PCM chunk in seconds |
| `decode_timeout_s` | `float` | `30.0` | Maximum decode time before raising a timeout error |
| `max_queue_depth` | `int \| None` | `None` | Cap on chunk queue depth; `None` means unlimited |

#### Returns

[`SourceIngestEnvelope`](#sourceingestenvelope) — the decoded MP3 wrapped in the shared envelope.

#### Raises

| Exception | Condition |
|-----------|-----------|
| `FileNotFoundError` | `source_path` does not exist |
| `DecodeFailedError` | ffmpeg rejected the source or returned a non-zero exit code |
| `DecodeTimeoutError` | ffmpeg exceeded `decode_timeout_s` |
| `ValueError` | `chunk_duration_s` ≤ 0 or produced an empty chunk |

#### Example

```python
from live_runtime.source_ingest import build_mp3_source_ingest

envelope = build_mp3_source_ingest(
    "fixtures/audio/test.mp3",
    target_sample_rate_hz=22050,
    chunk_duration_s=1.0,
    max_queue_depth=5,
)
print(envelope.decoded_audio.chunk_count)  # number of chunks
print(f"Ingest took {envelope.ingest_ms:.1f} ms")
```
