# stem_router

**File:** `live_runtime/stem_router.py`

Routes the four separated audio stems (vocals, drums, bass, other) to WAV files under an output directory. Uses a write-to-staging-then-rename pattern so that partial writes are never visible to readers — the final output files appear atomically.

The module writes silence for drums, bass, and other stems as a deterministic placeholder, while vocals receives the source PCM. This reflects the smoke/proof-of-pipeline contract: the separation model inference is deferred, but the artifact structure is fully exercised.

---

## Constants

| Name | Type | Value | Description |
|------|------|-------|-------------|
| `DEFAULT_VOCALS_NAME` | `str` | `"vocals.wav"` | Default output filename for the vocals stem |
| `DEFAULT_DRUMS_NAME` | `str` | `"drums.wav"` | Default output filename for the drums stem |
| `DEFAULT_BASS_NAME` | `str` | `"bass.wav"` | Default output filename for the bass stem |
| `DEFAULT_OTHER_NAME` | `str` | `"other.wav"` | Default output filename for the other stem |

---

## Exceptions

### `StemRoutingError`

Raised when stem output routing cannot be completed safely.

```python
@dataclass(frozen=True)
class StemRoutingError(RuntimeError):
    error_stage: str
    output_dir: Path
    message: str
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `error_stage` | `str` | Always `"output_write_failed"` |
| `output_dir` | `Path` | Directory where the write was attempted |
| `message` | `str` | Human-readable error (also the `str()` of the exception) |

---

## Functions

### `resolve_live_stem_routing`

```python
def resolve_live_stem_routing(
    output_dir: Path | str,
    *,
    vocals_name: str = DEFAULT_VOCALS_NAME,
    drums_name: str = DEFAULT_DRUMS_NAME,
    bass_name: str = DEFAULT_BASS_NAME,
    other_name: str = DEFAULT_OTHER_NAME,
) -> StemRouting
```

Compute the exact four live stem output paths under the requested output directory without writing any files. Use this when you need the `StemRouting` object for the result artifact but have already written the stems through another code path.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_dir` | `Path \| str` | — | Directory under which stem files will be (or are) located |
| `vocals_name` | `str` | `"vocals.wav"` | Filename for the vocals stem |
| `drums_name` | `str` | `"drums.wav"` | Filename for the drums stem |
| `bass_name` | `str` | `"bass.wav"` | Filename for the bass stem |
| `other_name` | `str` | `"other.wav"` | Filename for the other stem |

#### Returns

[`StemRouting`](contracts.md#stemrouting) — a frozen dataclass with the four absolute-or-relative paths.

#### Example

```python
from live_runtime.stem_router import resolve_live_stem_routing

routing = resolve_live_stem_routing("artifacts/live/run-001/")
# StemRouting(
#   vocals_path="artifacts/live/run-001/vocals.wav",
#   drums_path="artifacts/live/run-001/drums.wav",
#   bass_path="artifacts/live/run-001/bass.wav",
#   other_path="artifacts/live/run-001/other.wav",
# )
```

---

### `write_live_stems`

```python
def write_live_stems(
    source_ingest: SourceIngestEnvelope,
    output_dir: Path | str,
    *,
    vocals_name: str = DEFAULT_VOCALS_NAME,
    drums_name: str = DEFAULT_DRUMS_NAME,
    bass_name: str = DEFAULT_BASS_NAME,
    other_name: str = DEFAULT_OTHER_NAME,
) -> StemRouting
```

Write exactly four live stem WAV files from a pre-decoded source envelope and return the routing record. This is the main entry point for the stem output stage.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source_ingest` | `SourceIngestEnvelope` | — | Pre-decoded source from any ingest module |
| `output_dir` | `Path \| str` | — | Directory to write stem files into (created if it does not exist) |
| `vocals_name` | `str` | `"vocals.wav"` | Filename for the vocals stem |
| `drums_name` | `str` | `"drums.wav"` | Filename for the drums stem |
| `bass_name` | `str` | `"bass.wav"` | Filename for the bass stem |
| `other_name` | `str` | `"other.wav"` | Filename for the other stem |

#### Returns

[`StemRouting`](contracts.md#stemrouting) — the four final stem file paths.

#### Raises

| Exception | Condition |
|-----------|-----------|
| `StemRoutingError` | `output_dir` exists but is not a directory |
| `StemRoutingError` | Decoded audio metadata is invalid (zero frame width) |
| `StemRoutingError` | Decoded PCM is not frame-aligned |
| `StemRoutingError` | A filesystem write or rename operation fails (`FileNotFoundError` or `OSError`) |

#### Stem Content

| Stem | Content |
|------|---------|
| vocals | Full decoded PCM from `source_ingest.decoded_audio.pcm` |
| drums | Silence (all-zero bytes, same frame count as decoded PCM) |
| bass | Silence (all-zero bytes, same frame count as decoded PCM) |
| other | Silence (all-zero bytes, same frame count as decoded PCM) |

All four WAV files are mono, signed 16-bit (s16le), at `decoded_audio.sample_rate_hz`.

#### Write Safety

Files are first written to a temporary staging directory under the parent of `output_dir`, then renamed into place. If any write or rename fails, staged files are cleaned up and the error is re-raised as `StemRoutingError`. The final output directory will either contain all four files or none of them — it is never left in a half-written state.

#### Example

```python
from live_runtime.source_ingest import build_mp3_source_ingest
from live_runtime.stem_router import write_live_stems
from live_runtime.live_core import build_live_runtime_result

ingest = build_mp3_source_ingest("track.mp3", chunk_duration_s=1.0)
routing = write_live_stems(ingest, "artifacts/live/run-001/")
# Files written:
#   artifacts/live/run-001/vocals.wav
#   artifacts/live/run-001/drums.wav
#   artifacts/live/run-001/bass.wav
#   artifacts/live/run-001/other.wav

result = build_live_runtime_result(ingest, chunk_duration_s=1.0, stem_routing=routing)
```
