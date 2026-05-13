# live_runtime API Reference

The `live_runtime` package is the core runtime library for audio source separation. It ingests audio from MP3 files, microphones, or video containers, coordinates model path resolution, and emits structured JSON artifacts with four separated stems (vocals, drums, bass, other).

## Module Index

| Module | File | Purpose |
|--------|------|---------|
| [contracts](contracts.md) | `contracts.py` | Frozen dataclasses, type aliases, schema loading, and validation |
| [live_core](live_core.md) | `live_core.py` | Model path resolution and runtime result assembly |
| [source_ingest](source_ingest.md) | `source_ingest.py` | Source-agnostic ingest envelope and MP3 convenience helpers |
| [mp3_ingest](mp3_ingest.md) | `mp3_ingest.py` | ffmpeg-based audio decoding and PCM chunk construction |
| [mic_ingest](mic_ingest.md) | `mic_ingest.py` | Microphone capture via sounddevice with a fake backend for tests |
| [video_ingest](video_ingest.md) | `video_ingest.py` | Video container audio extraction |
| [stem_router](stem_router.md) | `stem_router.py` | WAV stem writing and output path routing |
| [umx_separator](umx_separator.md) | `umx_separator.py` | Optional Open-Unmix `umxhq` full-mode separation (Torch extra) |

## Package Structure

```
live_runtime/
├── __init__.py
├── contracts.py      # Type system + schema validation
├── live_core.py      # Orchestration entry point
├── source_ingest.py  # Source-agnostic envelope
├── mp3_ingest.py     # ffmpeg decode pipeline
├── mic_ingest.py     # sounddevice capture pipeline
├── video_ingest.py   # Video audio extraction
├── stem_router.py    # Stem WAV output (+ mix WAV helper)
└── umx_separator.py  # Full-mode umxhq (optional torch/openunmix)
```

## Typical Workflow

```python
from live_runtime.source_ingest import build_mp3_source_ingest
from live_runtime.live_core import build_live_runtime_result
from live_runtime.stem_router import write_live_stems
from live_runtime.contracts import validate_live_runtime_result
import json

# 1. Decode source
ingest = build_mp3_source_ingest("track.mp3", chunk_duration_s=1.0)

# 2. Write four stem WAVs
routing = write_live_stems(ingest, "artifacts/live/run-001/")

# 3. Build and validate the JSON artifact
result = build_live_runtime_result(ingest, chunk_duration_s=1.0, stem_routing=routing)
payload = result.to_dict()
validate_live_runtime_result(payload)

# 4. Persist
with open("artifacts/live/run-001/live_runtime_result.json", "w") as f:
    json.dump(payload, f, indent=2)
```

## Artifact Schema

The live runtime emits a JSON artifact validated by
`artifacts/schema/live_runtime_result.schema.json`. Key top-level fields:

| Field | Type | Description |
|-------|------|-------------|
| `source` | object | Source kind, reference, and optional metadata |
| `input` | string | Path or device reference |
| `sample_rate_hz` | integer | Sample rate of the decoded audio |
| `chunk_duration_s` | float | Duration of each processing chunk |
| `chunk_index` | integer | Index of the last processed chunk |
| `stft_ms` | float | Ingest stage timing (ms) |
| `infer_ms` | float | Inference stage timing (ms) |
| `istft_ms` | float | Post-processing timing (ms) |
| `total_ms` | float | Sum of all timing stages |
| `status` | string | `"ok"` or `"error"` |
| `error_stage` | string\|null | Stage name if an error occurred |
| `error_message` | string\|null | Human-readable error detail |
| `timestamp` | string | ISO-8601 UTC timestamp |
| `health_state` | string | `"healthy"`, `"degraded"`, or `"fallback"` |
| `health_reason` | string | Explanation of current health state |
| `requested_model_path` | string | Model path as requested by the caller |
| `fallback_applied` | boolean | Whether fallback to default model was used |
| `queue_depth` | integer | Number of chunks queued at last chunk |
| `drop_count` | integer | Number of chunks dropped due to backpressure |
| `model_path` | string | Effective model path used |
| `stem_paths` | object | Paths to the four output WAV files |
| `metadata` | object | Device, mode, clock, sample, and stage metadata |
