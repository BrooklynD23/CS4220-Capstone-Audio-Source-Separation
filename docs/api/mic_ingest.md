# mic_ingest

**File:** `live_runtime/mic_ingest.py`

Implements microphone audio capture via the `sounddevice` backend and converts it into the shared `SourceIngestEnvelope`. Provides a `MicCaptureBackend` protocol for dependency injection, a deterministic `FakeMicCaptureBackend` for tests and CI, and a `SoundDeviceMicCaptureBackend` for real hardware.

The `sounddevice` package is an optional dependency. Install with `pip install -e .[mic]` to enable real device capture.

---

## Constants

| Name | Type | Value | Description |
|------|------|-------|-------------|
| `DEFAULT_MIC_KIND` | `str` | `"mic"` | Source kind string for microphone sources |
| `DEFAULT_MIC_BACKEND` | `str` | `"sounddevice"` | Default capture backend identifier |
| `DEFAULT_MIC_CAPTURE_DURATION_S` | `float` | `1.0` | Default capture duration in seconds |

---

## Exceptions

All exceptions are frozen dataclasses and subclass `RuntimeError`.

### `MicCaptureError`

Base exception for microphone capture failures that should be surfaced in runtime telemetry.

```python
@dataclass(frozen=True)
class MicCaptureError(RuntimeError):
    error_stage: str
    device_reference: str
    backend_name: str
    message: str
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `error_stage` | `str` | Stage identifier (e.g. `"capture_failed"`, `"capture_timeout"`) |
| `device_reference` | `str` | Device identifier that triggered the error |
| `backend_name` | `str` | Capture backend that raised the error |
| `message` | `str` | Human-readable error (also the `str()` of the exception) |

---

### `MicCaptureFailedError`

Raised when the capture backend rejects or cannot open the requested device, when `sounddevice` is not installed, when the returned audio format is unsupported, or when no audio was captured.

```python
@dataclass(frozen=True)
class MicCaptureFailedError(MicCaptureError):
    ...
```

Inherits all fields from `MicCaptureError`. `error_stage` is always `"capture_failed"`.

---

### `MicCaptureTimeoutError`

Raised when microphone capture exceeds the allowed capture timeout.

```python
@dataclass(frozen=True)
class MicCaptureTimeoutError(MicCaptureError):
    ...
```

Inherits all fields from `MicCaptureError`. `error_stage` is always `"capture_timeout"`.

---

## Dataclasses

### `CapturedMicAudio`

Raw PCM bytes returned from a capture backend.

```python
@dataclass(frozen=True)
class CapturedMicAudio:
    pcm: bytes
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    backend_name: str
    device_reference: str
    capture_duration_s: float
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `pcm` | `bytes` | Raw mono s16le PCM bytes |
| `sample_rate_hz` | `int` | Sample rate returned by the capture backend |
| `channels` | `int` | Channel count (must be `1`) |
| `sample_width_bytes` | `int` | Bytes per sample (must be `2`) |
| `backend_name` | `str` | Identifier of the backend that captured the audio |
| `device_reference` | `str` | Device identifier as provided to `capture()` |
| `capture_duration_s` | `float` | Actual capture duration in seconds |

---

## Protocols

### `MicCaptureBackend`

Backend interface for capturing a short PCM buffer from a microphone device. Implement this protocol to inject custom capture logic.

```python
class MicCaptureBackend(Protocol):
    backend_name: str

    def capture(
        self,
        device_reference: str,
        *,
        sample_rate_hz: int,
        capture_duration_s: float,
        capture_timeout_s: float,
    ) -> CapturedMicAudio: ...
```

#### `capture` Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `device_reference` | `str` | Device identifier or `"default"` for the system default |
| `sample_rate_hz` | `int` | Requested sample rate |
| `capture_duration_s` | `float` | How many seconds to capture |
| `capture_timeout_s` | `float` | Maximum wall-clock time for the capture call |

#### `capture` Returns

[`CapturedMicAudio`](#capturedmicaudio)

---

## Classes

### `FakeMicCaptureBackend`

Deterministic capture backend for tests and CI. Returns a buffer of silence (all-zero bytes) of the expected length. Does not require `sounddevice` or any hardware.

```python
@dataclass(frozen=True)
class FakeMicCaptureBackend:
    backend_name: str = "fake"
    tone_hz: float = 440.0
```

#### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `backend_name` | `str` | `"fake"` | Backend identifier reported in captured audio |
| `tone_hz` | `float` | `440.0` | Reserved; currently unused (always emits silence) |

#### `capture` Behavior

Returns `frame_count = max(1, round(sample_rate_hz * capture_duration_s))` frames of `\x00\x00` (silence). `capture_timeout_s` is ignored.

#### Example

```python
from live_runtime.mic_ingest import FakeMicCaptureBackend, build_mic_source_ingest

envelope = build_mic_source_ingest(
    "default",
    backend=FakeMicCaptureBackend(),
    target_sample_rate_hz=16000,
    chunk_duration_s=1.0,
    capture_duration_s=1.0,
)
print(envelope.decoded_audio.total_frames)  # 16000
```

---

### `SoundDeviceMicCaptureBackend`

Captures PCM from a real microphone device via the `sounddevice` library. The capture runs in a daemon thread and is killed via `sd.stop()` if it exceeds `capture_timeout_s`.

```python
class SoundDeviceMicCaptureBackend:
    backend_name = DEFAULT_MIC_BACKEND  # "sounddevice"
```

#### `capture` Raises

| Exception | Condition |
|-----------|-----------|
| `MicCaptureFailedError` | `sample_rate_hz` ≤ 0 or `capture_duration_s` ≤ 0 |
| `MicCaptureFailedError` | `sounddevice` is not installed |
| `MicCaptureTimeoutError` | Capture thread exceeded `capture_timeout_s` |
| `MicCaptureFailedError` | `sounddevice` raised an exception during capture |
| `MicCaptureFailedError` | Capture returned empty audio |

#### Device Reference

Pass `""` or `"default"` to use the system default input device. Any other string is passed directly to `sd.rec(device=...)`.

---

## Functions

### `build_mic_source_descriptor`

```python
def build_mic_source_descriptor(
    device_reference: str,
    *,
    backend_name: str,
    capture_duration_s: float,
    sample_rate_hz: int,
) -> SourceDescriptor
```

Create the `SourceDescriptor` for a microphone capture.

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `device_reference` | `str` | Device identifier (used as both `reference` and in `metadata`) |
| `backend_name` | `str` | Backend name stored in `metadata` |
| `capture_duration_s` | `float` | Capture duration stored in `metadata` |
| `sample_rate_hz` | `int` | Sample rate stored in `metadata` |

#### Returns

[`SourceDescriptor`](contracts.md#sourcedescriptor) with `kind="mic"` and `metadata` containing `backend`, `device`, `capture_duration_s`, and `sample_rate_hz`.

---

### `build_mic_source_ingest`

```python
def build_mic_source_ingest(
    device_reference: str,
    *,
    backend: MicCaptureBackend | None = None,
    target_sample_rate_hz: int = 44100,
    chunk_duration_s: float = 1.0,
    capture_duration_s: float = DEFAULT_MIC_CAPTURE_DURATION_S,
    capture_timeout_s: float = 30.0,
    max_queue_depth: int | None = None,
) -> SourceIngestEnvelope
```

Capture microphone PCM and convert it into the shared ingest envelope. Uses `SoundDeviceMicCaptureBackend` by default; pass `backend=FakeMicCaptureBackend()` for tests.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `device_reference` | `str` | — | Device identifier or `"default"` |
| `backend` | `MicCaptureBackend \| None` | `None` | Capture backend; defaults to `SoundDeviceMicCaptureBackend()` |
| `target_sample_rate_hz` | `int` | `44100` | Target sample rate for both capture and PCM output |
| `chunk_duration_s` | `float` | `1.0` | Duration of each output PCM chunk in seconds |
| `capture_duration_s` | `float` | `1.0` | How long to record from the microphone |
| `capture_timeout_s` | `float` | `30.0` | Maximum wall-clock time allowed for the capture call |
| `max_queue_depth` | `int \| None` | `None` | Cap on chunk queue depth |

#### Returns

[`SourceIngestEnvelope`](source_ingest.md#sourceingestenvelope) — captured audio wrapped in the shared envelope.

#### Raises

| Exception | Condition |
|-----------|-----------|
| `MicCaptureFailedError` | Capture failed for any reason (see backend docs) |
| `MicCaptureTimeoutError` | Capture exceeded `capture_timeout_s` |
| `MicCaptureFailedError` | Backend returned channels ≠ 1 or sample_width_bytes ≠ 2 |
| `MicCaptureFailedError` | Backend returned a sample rate different from `target_sample_rate_hz` |
| `MicCaptureFailedError` | PCM chunking failed (wraps `DecodeFailedError`) |

#### Example

```python
from live_runtime.mic_ingest import build_mic_source_ingest, FakeMicCaptureBackend
from live_runtime.live_core import build_live_runtime_result

# In tests: use the fake backend
envelope = build_mic_source_ingest(
    "default",
    backend=FakeMicCaptureBackend(),
    target_sample_rate_hz=16000,
    chunk_duration_s=0.5,
    capture_duration_s=1.0,
)

result = build_live_runtime_result(envelope, chunk_duration_s=0.5)
```
