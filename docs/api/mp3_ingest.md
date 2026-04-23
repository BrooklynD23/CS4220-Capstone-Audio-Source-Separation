# mp3_ingest

**File:** `live_runtime/mp3_ingest.py`

Implements the ffmpeg-based audio decode pipeline. Takes any ffmpeg-readable audio source, converts it to mono s16le PCM at a target sample rate, and slices it into fixed-duration chunks with queue depth and drop count telemetry. `decode_mp3_to_pcm` is the primary public entry point; `build_decoded_audio_from_pcm` is exposed for callers that already have raw PCM bytes (e.g. the mic ingest path).

---

## Constants

| Name | Type | Value | Description |
|------|------|-------|-------------|
| `DEFAULT_TARGET_SAMPLE_RATE_HZ` | `Final[int]` | `44100` | Default PCM output sample rate |
| `DEFAULT_DECODE_TIMEOUT_S` | `Final[float]` | `30.0` | Default ffmpeg subprocess timeout in seconds |

---

## Exceptions

All exceptions are frozen dataclasses and subclass `RuntimeError`.

### `DecodeError`

Base exception for decode failures that should be surfaced in runtime telemetry.

```python
@dataclass(frozen=True)
class DecodeError(RuntimeError):
    error_stage: str
    source_path: Path
    codec_context: str
    message: str
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `error_stage` | `str` | Pipeline stage identifier (e.g. `"decode_failed"`, `"decode_timeout"`) |
| `source_path` | `Path` | Path of the source file that caused the error |
| `codec_context` | `str` | ffmpeg stderr output or other low-level context |
| `message` | `str` | Human-readable error message (also the `str()` of the exception) |

---

### `DecodeFailedError`

Raised when ffmpeg rejects the source media (non-zero exit code, empty PCM, or misaligned frames).

```python
@dataclass(frozen=True)
class DecodeFailedError(DecodeError):
    ...
```

Inherits all fields from `DecodeError`. `error_stage` is always `"decode_failed"`.

---

### `DecodeTimeoutError`

Raised when the ffmpeg subprocess exceeds the allowed timeout.

```python
@dataclass(frozen=True)
class DecodeTimeoutError(DecodeError):
    ...
```

Inherits all fields from `DecodeError`. `error_stage` is always `"decode_timeout"`.

---

## Dataclasses

### `DecodedChunk`

Describes one deterministic PCM chunk produced from the decoded clip.

```python
@dataclass(frozen=True)
class DecodedChunk:
    chunk_index: int
    frame_offset: int
    frame_count: int
    queue_depth: int
    drop_count: int
    pcm: bytes
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `chunk_index` | `int` | Zero-based chunk index |
| `frame_offset` | `int` | Frame offset within the full decoded PCM |
| `frame_count` | `int` | Number of PCM frames in this chunk |
| `queue_depth` | `int` | Effective queue depth at this chunk (capped by `max_queue_depth` if set) |
| `drop_count` | `int` | Number of chunks dropped due to `max_queue_depth` backpressure |
| `pcm` | `bytes` | Raw PCM bytes for this chunk (mono s16le) |

---

### `DecodedAudio`

Decoded PCM audio together with its fixed-duration chunk view.

```python
@dataclass(frozen=True)
class DecodedAudio:
    source_path: Path
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    chunk_duration_s: float
    total_frames: int
    pcm: bytes
    chunks: tuple[DecodedChunk, ...]
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `source_path` | `Path` | Normalized path of the decoded source |
| `sample_rate_hz` | `int` | Sample rate of the decoded PCM |
| `channels` | `int` | Number of channels (always `1` — mono) |
| `sample_width_bytes` | `int` | Bytes per sample (always `2` — int16) |
| `chunk_duration_s` | `float` | Duration used to slice the PCM into chunks |
| `total_frames` | `int` | Total number of PCM frames decoded |
| `pcm` | `bytes` | Complete raw PCM bytes (mono s16le) |
| `chunks` | `tuple[DecodedChunk, ...]` | Ordered tuple of all fixed-duration chunks |

#### Properties

##### `chunk_count -> int`

Number of chunks in `chunks`.

```python
audio: DecodedAudio = ...
print(audio.chunk_count)  # e.g. 42
```

---

## Functions

### `build_decoded_audio_from_pcm`

```python
def build_decoded_audio_from_pcm(
    source_path: Path | str,
    pcm: bytes,
    *,
    target_sample_rate_hz: int = DEFAULT_TARGET_SAMPLE_RATE_HZ,
    chunk_duration_s: float = 1.0,
    max_queue_depth: int | None = None,
) -> DecodedAudio
```

Build the `DecodedAudio` envelope from already-decoded PCM bytes. Used by the mic ingest path to wrap captured audio in the standard structure without calling ffmpeg.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source_path` | `Path \| str` | — | Logical source path (used in error messages and the envelope) |
| `pcm` | `bytes` | — | Raw mono s16le PCM bytes |
| `target_sample_rate_hz` | `int` | `44100` | Sample rate that the PCM was captured/decoded at |
| `chunk_duration_s` | `float` | `1.0` | Duration of each output chunk in seconds |
| `max_queue_depth` | `int \| None` | `None` | Cap on queue depth; affects `drop_count` in each chunk |

#### Returns

[`DecodedAudio`](#decodedaudio) — fully constructed envelope.

#### Raises

| Exception | Condition |
|-----------|-----------|
| `ValueError` | `chunk_duration_s` ≤ 0 |
| `DecodeFailedError` | PCM bytes are not aligned to 16-bit (2-byte) frames |
| `DecodeFailedError` | PCM contains no frames |
| `ValueError` | `chunk_duration_s` produces an empty chunk (too short for the sample rate) |

#### Example

```python
from live_runtime.mp3_ingest import build_decoded_audio_from_pcm

# 1 second of silence at 16 kHz mono s16le
pcm = b"\x00\x00" * 16000
audio = build_decoded_audio_from_pcm("device:default", pcm, target_sample_rate_hz=16000)
print(audio.chunk_count)    # 1
print(audio.total_frames)   # 16000
```

---

### `decode_audio_to_pcm`

```python
def decode_audio_to_pcm(
    source_path: Path | str,
    *,
    target_sample_rate_hz: int = DEFAULT_TARGET_SAMPLE_RATE_HZ,
    chunk_duration_s: float = 1.0,
    decode_timeout_s: float = DEFAULT_DECODE_TIMEOUT_S,
    max_queue_depth: int | None = None,
) -> DecodedAudio
```

Decode any ffmpeg-readable audio source into mono PCM and fixed-duration chunks. Supports MP3, WAV, FLAC, AAC, and any container readable by the installed ffmpeg binary.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source_path` | `Path \| str` | — | Path to the audio file |
| `target_sample_rate_hz` | `int` | `44100` | Target sample rate for PCM resampling |
| `chunk_duration_s` | `float` | `1.0` | Duration of each output chunk in seconds |
| `decode_timeout_s` | `float` | `30.0` | ffmpeg subprocess timeout |
| `max_queue_depth` | `int \| None` | `None` | Cap on chunk queue depth |

#### Returns

[`DecodedAudio`](#decodedaudio).

#### Raises

| Exception | Condition |
|-----------|-----------|
| `FileNotFoundError` | `source_path` does not exist on disk |
| `FileNotFoundError` | ffmpeg binary not found (neither bundled via imageio-ffmpeg nor on PATH) |
| `DecodeFailedError` | ffmpeg exited with a non-zero return code |
| `DecodeTimeoutError` | ffmpeg exceeded `decode_timeout_s` |
| `DecodeFailedError` | Decoded PCM was not frame-aligned or contained no frames |

#### ffmpeg invocation

The subprocess is called as:

```
ffmpeg -hide_banner -loglevel error -i <source> -vn -ac 1 -ar <rate> -f s16le pipe:1
```

Output format: mono (`-ac 1`), signed 16-bit little-endian (`-f s16le`), written to stdout.

---

### `decode_mp3_to_pcm`

```python
def decode_mp3_to_pcm(
    source_path: Path | str,
    *,
    target_sample_rate_hz: int = DEFAULT_TARGET_SAMPLE_RATE_HZ,
    chunk_duration_s: float = 1.0,
    decode_timeout_s: float = DEFAULT_DECODE_TIMEOUT_S,
    max_queue_depth: int | None = None,
) -> DecodedAudio
```

Decode an MP3 clip into mono PCM and emit deterministic fixed-duration chunks. This is a thin alias over `decode_audio_to_pcm` with an MP3-specific name for call-site clarity.

#### Parameters

Identical to [`decode_audio_to_pcm`](#decode_audio_to_pcm).

#### Returns

[`DecodedAudio`](#decodedaudio).

#### Raises

Same as [`decode_audio_to_pcm`](#decode_audio_to_pcm).

#### Example

```python
from live_runtime.mp3_ingest import decode_mp3_to_pcm

audio = decode_mp3_to_pcm(
    "fixtures/audio/test.mp3",
    target_sample_rate_hz=22050,
    chunk_duration_s=1.0,
)
print(f"{audio.total_frames} frames, {audio.chunk_count} chunks")
print(f"First chunk drop_count: {audio.chunks[0].drop_count}")
```

---

## Queue Depth and Drop Count Semantics

When `max_queue_depth` is `None`, `queue_depth` increments by 1 for each chunk and `drop_count` is always 0.

When `max_queue_depth` is set:

- `queue_depth` is capped at `max_queue_depth`.
- `drop_count` for chunk `i` is `max(0, (i + 1) - max_queue_depth)`.

This simulates real-time backpressure: chunks beyond the queue limit are counted as dropped.

```python
audio = decode_mp3_to_pcm("track.mp3", max_queue_depth=3)
# chunk 0: queue_depth=1, drop_count=0
# chunk 1: queue_depth=2, drop_count=0
# chunk 2: queue_depth=3, drop_count=0
# chunk 3: queue_depth=3, drop_count=1
# chunk 4: queue_depth=3, drop_count=2
```
