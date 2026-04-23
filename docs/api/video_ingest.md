# video_ingest

**File:** `live_runtime/video_ingest.py`

Implements audio extraction from video container files (MP4, MKV, MOV, AVI, etc.) via ffmpeg. The extracted audio is decoded to mono PCM and wrapped in the shared `SourceIngestEnvelope`, identical in structure to the MP3 ingest path.

Video files are treated as audio sources — the video track is discarded (`-vn` ffmpeg flag). Any container supported by the installed ffmpeg binary is accepted.

---

## Constants

| Name | Type | Value | Description |
|------|------|-------|-------------|
| `DEFAULT_VIDEO_KIND` | `str` | `"video_audio"` | Source kind string for video container sources |

---

## Dataclasses

### `VideoSourceConfig`

Captures the file-backed video source metadata used by the CLI.

```python
@dataclass(frozen=True)
class VideoSourceConfig:
    reference: str
    container: str
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `reference` | `str` | Path to the video file |
| `container` | `str` | Container format derived from the file extension (e.g. `"mp4"`, `"mkv"`) |

---

## Functions

### `build_video_source_descriptor`

```python
def build_video_source_descriptor(source_path: Path | str) -> SourceDescriptor
```

Create the `SourceDescriptor` for a video container with an audio track.

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `source_path` | `Path \| str` | Path to the video file |

#### Returns

[`SourceDescriptor`](contracts.md#sourcedescriptor) with:
- `kind = "video_audio"`
- `reference = str(Path(source_path))`
- `metadata = {"container": <ext>}` where `<ext>` is the lowercase file extension without the leading dot, defaulting to `"mp4"` if there is no extension.

#### Container Detection

The container is derived from `Path(source_path).suffix.lstrip(".").lower()`. If the path has no extension, `"mp4"` is used as the default.

#### Example

```python
from live_runtime.video_ingest import build_video_source_descriptor

desc = build_video_source_descriptor("footage/clip.mkv")
# SourceDescriptor(kind="video_audio", reference="footage/clip.mkv",
#                  metadata={"container": "mkv"})

desc = build_video_source_descriptor("footage/clip")
# SourceDescriptor(kind="video_audio", reference="footage/clip",
#                  metadata={"container": "mp4"})
```

---

### `build_video_source_ingest`

```python
def build_video_source_ingest(
    source_path: Path | str,
    *,
    target_sample_rate_hz: int = 44100,
    chunk_duration_s: float = 1.0,
    decode_timeout_s: float = 30.0,
    max_queue_depth: int | None = None,
) -> SourceIngestEnvelope
```

Decode audio from a video container into the shared ingest envelope. Internally calls `decode_audio_to_pcm` via `build_source_ingest`, so the same ffmpeg pipeline is used as for MP3 sources.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source_path` | `Path \| str` | — | Path to the video file |
| `target_sample_rate_hz` | `int` | `44100` | Target sample rate for PCM output |
| `chunk_duration_s` | `float` | `1.0` | Duration of each output chunk in seconds |
| `decode_timeout_s` | `float` | `30.0` | ffmpeg subprocess timeout |
| `max_queue_depth` | `int \| None` | `None` | Cap on chunk queue depth |

#### Returns

[`SourceIngestEnvelope`](source_ingest.md#sourceingestenvelope) — decoded audio wrapped in the shared envelope with `source.kind="video_audio"`.

#### Raises

| Exception | Condition |
|-----------|-----------|
| `FileNotFoundError` | `source_path` does not exist on disk |
| `FileNotFoundError` | ffmpeg binary not found |
| `DecodeFailedError` | ffmpeg exited with a non-zero return code |
| `DecodeTimeoutError` | ffmpeg exceeded `decode_timeout_s` |
| `DecodeFailedError` | Decoded PCM was not frame-aligned or contained no frames |

#### Example

```python
from live_runtime.video_ingest import build_video_source_ingest
from live_runtime.live_core import build_live_runtime_result

envelope = build_video_source_ingest(
    "footage/interview.mp4",
    target_sample_rate_hz=22050,
    chunk_duration_s=1.0,
)

result = build_live_runtime_result(envelope, chunk_duration_s=1.0)
print(result.to_dict()["source"])
# {"kind": "video_audio", "reference": "footage/interview.mp4",
#  "metadata": {"container": "mp4"}}
```
