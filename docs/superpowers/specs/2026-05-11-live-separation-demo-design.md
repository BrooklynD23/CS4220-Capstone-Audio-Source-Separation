# Live Separation Demo — Design Spec

**Date:** 2026-05-11
**Branch:** final-evidence-ui-pass
**Status:** Approved

---

## 1. Goal

Deliver two complementary artifacts that satisfy the PM's requirement for a separated vocal output demo:

1. **Web UI demo page** (`ui/demo/`) — browser-based MP3 upload, full GPU separation pipeline, per-stem waveform + spectrogram lanes with individual playback, performance overlay, GPU vs CPU benchmark table.
2. **Python desktop app** (`scripts/ui/live_demo.py`) — standalone matplotlib 3-panel animated spectrogram + PyAudio dual-stream playback, GPU utilization overlay, optional microphone input.

Additionally, fix the batch file URL-encoding bug in `run_local_demo.bat` that leaves `?artifact=` empty.

---

## 2. Architecture

```
run_local_demo.bat  (fixed)
      │
      └─► scripts/ui/serve_compare_demo.py  (upgraded — same port 8000)
               ├─ GET  /ui/compare/          → existing compare shell (unchanged)
               ├─ GET  /ui/demo/             → new live demo page
               ├─ POST /api/separate         → MP3 upload → UMX → stems + JSON
               └─ GET  /artifacts/**         → serves generated stems + JSON

scripts/ui/live_demo.py  (new — standalone desktop app)
      └─► matplotlib 3-panel + PyAudio dual-stream playback

ui/demo/index.html + ui/demo/app.js  (new — focused demo page)
ui/shared/audio-render.js            (new — shared waveform/spectrogram drawing)

scripts/ui/encode_artifact_path.py   (new — batch file URL-encoding helper)
```

---

## 3. Batch File Fix

**Problem:** `run_local_demo.bat` uses `for /f` with backtick syntax to URL-encode the artifact path via an inline Python one-liner. When the Python executable path contains spaces and requires quoting, CMD mis-parses the backtick command, leaving `ENCODED_ARTIFACT_PATH` empty and producing `?artifact=` with no value.

**Fix:** Extract the one-liner into `scripts/ui/encode_artifact_path.py`. The batch file calls it as:

```batch
for /f "usebackq delims=" %%I in (
  `"%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\ui\encode_artifact_path.py" "%PROJECT_ROOT%" "%ARTIFACT_PATH%"`
) do set "ENCODED_ARTIFACT_PATH=%%I"
```

`encode_artifact_path.py` accepts two positional args (repo root, artifact path) and prints the URL-encoded relative path (e.g. `/artifacts/live/one-click/live_runtime_result.json`). Paths outside the repo root exit with code 1.

---

## 4. Server Upgrade (`serve_compare_demo.py`)

`CompareDemoHandler` gains a `do_POST` method that handles `POST /api/separate`:

### Request
- `Content-Type: multipart/form-data`
- Fields: `file` (MP3 bytes, required), `device` (`gpu` or `cpu`, default `gpu`)
- Max size: 50 MB — server returns HTTP 413 before reading body if `Content-Length` exceeds limit

### Processing
1. Parse multipart body using `cgi.FieldStorage` (stdlib, deprecated but present in Python 3.10–3.12; our supported range excludes 3.13 where it is removed)
2. Write MP3 to `artifacts/live/demo-<uuid>/input.mp3`
3. Re-encode MP3 → `mix.wav` via ffmpeg (reuses `mp3_ingest._resolve_ffmpeg_executable`)
4. Resolve device via `umx_separator.resolve_device(device)`
5. Load UMX separator if not already cached: a module-level dict `_SEPARATOR_CACHE: dict[str, Any]` keyed by device string holds loaded separators; populated lazily on first POST, reused on subsequent requests
6. Run `umx_separator.separate_tensor` on the full audio tensor
7. Write 4 stems via `write_live_stems_from_arrays`
8. Write `live_runtime_result.json` via `_write_json_atomic`
9. Return 200 JSON:

```json
{
  "artifact_path": "artifacts/live/demo-<uuid>/live_runtime_result.json",
  "stem_urls": {
    "input":  "artifacts/live/demo-<uuid>/mix.wav",
    "vocals": "artifacts/live/demo-<uuid>/vocals.wav",
    "drums":  "artifacts/live/demo-<uuid>/drums.wav",
    "bass":   "artifacts/live/demo-<uuid>/bass.wav",
    "other":  "artifacts/live/demo-<uuid>/other.wav"
  },
  "timings": {
    "stft_ms": 0.0,
    "infer_ms": 340.0,
    "istft_ms": 0.0,
    "total_ms": 340.0
  },
  "device_used": "cuda"
}
```

### Error responses
- HTTP 400: missing `file` field, unreadable MP3, ffmpeg decode failure
- HTTP 413: body exceeds 50 MB
- HTTP 500: separation failure (model not loaded, CUDA OOM, etc.)
- All errors: `{"error": "<human-readable message>"}`

All GET requests continue to be handled by the existing static file logic unchanged.

---

## 5. Shared Audio Rendering Module (`ui/shared/audio-render.js`)

Extract `drawWaveform` and `drawSpectrogram` from `ui/compare/app.js` into a shared ES module so both the compare shell and the demo page use identical rendering code without duplication.

`ui/compare/app.js` imports them:
```js
import { drawWaveform, drawSpectrogram } from '../shared/audio-render.js';
```

`ui/demo/app.js` imports them the same way.

The functions' signatures and behavior are unchanged.

---

## 6. Web UI Demo Page (`ui/demo/`)

### Layout

Single scrolling page, dark theme consistent with compare shell. Four sections revealed progressively:

**Step 1 — Upload**
- File picker (accepts `.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`)
- Device selector: GPU / CPU (default GPU)
- "Separate" primary button; disabled until file selected
- Status line: "Awaiting file…" → spinner + elapsed counter during separation → "Done in 4.2s" on success

**Step 2 — Waveform Lanes** (revealed after separation)
- Five lanes: Input, Vocals, Drums, Bass, Other
- Each lane: label | waveform canvas (640×96) | spectrogram canvas (640×80) | Play/Pause button
- Clicking Play on a lane starts audio playback for that stem's WAV URL
- Playing a second lane pauses the first (single active stream at a time)
- WAV files decoded and rendered using `drawWaveform` / `drawSpectrogram` from shared module

**Step 3 — Performance Overlay**
- Reads from the API response `timings` + `device_used`
- Displays: STFT ms | Infer ms | ISTFT ms | Total ms | Device | Chunk duration

**Step 4 — Benchmark Table**
- Fetches `artifacts/bench/capstone_evidence_manifest.json` from the server
- Renders a table: Backend | Chunk (ms) | Speedup | SDR
- SDR shown if present in manifest, "—" otherwise
- Table shown even if manifest is missing (shows "Benchmark data unavailable")

### Navigation
- "← Compare shell" link in the header pointing to `/ui/compare/`
- Compare shell gets a symmetric "→ Live Demo" link pointing to `/ui/demo/`

---

## 7. Python Desktop App (`scripts/ui/live_demo.py`)

### Invocation
```bash
python scripts/ui/live_demo.py --input song.mp3 [--device gpu|cpu] [--mic]
```

### Flow
1. Print "Separating…" to terminal; run full UMX separation (reuses `umx_separator`)
2. Pre-compute spectrograms for mix, vocal mask, and vocal output using `librosa.stft`
   - Mix: `stft(mix)`
   - Vocal mask: `|vocal_estimate| / (|mix| + 1e-7)` clipped to [0, 1]
   - Vocal output: `stft(vocal_stem)`
3. Open matplotlib figure (3 rows × 1 col) with a performance text box overlay
4. Start two PyAudio output streams (callback-based, non-blocking):
   - Stream A: vocals float32 PCM
   - Stream B: bass + drums + other summed and normalized, as instrumental
   - Both start simultaneously from position 0
5. `FuncAnimation` advances a vertical cursor line on all 3 panels each tick (50ms interval)
6. Performance text box updated each tick: chunk latency from JSON, GPU util % via `pynvml`

### 3-Panel Spectrogram Figure
```
Row 0: Input Mix Spectrogram      — full frequency range, log scale
Row 1: Predicted Vocal Mask       — 0→1 heatmap (viridis colormap)
Row 2: Separated Vocal Output     — frequency range, log scale
```

### `--mic` mode
- Captures 5 seconds of mic audio via `sounddevice.rec` (reuses `mic_ingest` patterns)
- Runs separation on the captured clip
- Displays the same 3-panel figure, plays back vocals vs instrumental
- No real-time capture+separation loop (separation runs on the full 5s clip)
- Instrumental = bass + drums + other summed and normalized, identical to main mode

### Graceful degradation
- `pynvml` unavailable → GPU overlay shows "GPU: N/A"
- `pyaudio` unavailable → prints install instructions, exits with code 1 before opening figure
- `librosa` unavailable → prints install instructions, exits with code 1
- GPU unavailable → falls back to CPU, prints warning

### New dependencies (added to `[gpu]` extra in `pyproject.toml`)
- `matplotlib>=3.8`
- `librosa>=0.10`
- `PyAudio>=0.2.14`
- `pynvml>=11.0` (optional — imported with try/except)

---

## 8. Error Handling Summary

| Scenario | Web UI | Desktop app |
|---|---|---|
| No file selected | Button disabled | N/A |
| File > 50 MB | Error banner (HTTP 413) | N/A |
| ffmpeg decode failure | Error banner (HTTP 400) | Prints error, exits |
| CUDA OOM | Error banner (HTTP 500) | Falls back to CPU |
| pynvml missing | N/A | "GPU: N/A" in overlay |
| pyaudio missing | N/A | Prints instructions, exits |
| Benchmark manifest missing | "Benchmark data unavailable" | N/A |

---

## 9. Testing

| Test file | What it covers |
|---|---|
| `tests/ui/test_demo_api.py` | POST /api/separate: valid MP3 → 200 + JSON shape; missing file → 400; oversized → 413 |
| `tests/ui/test_encode_artifact_path.py` | Paths with spaces, unicode, paths outside repo root |
| `tests/ui/` existing Playwright tests | Compare shell — must remain passing; no regressions |
| `live_demo.py` | No automated test; manual verification checklist in README |

---

## 10. Files Changed / Created

| File | Change |
|---|---|
| `run_local_demo.bat` | Fix `for /f` URL-encoding to use helper script |
| `scripts/ui/encode_artifact_path.py` | New — URL-encoding helper for batch file |
| `scripts/ui/serve_compare_demo.py` | Add `do_POST` for `/api/separate`; cache separator |
| `ui/shared/audio-render.js` | New — extract `drawWaveform` + `drawSpectrogram` |
| `ui/compare/app.js` | Import from shared module (remove duplicated functions) |
| `ui/compare/index.html` | Add "→ Live Demo" nav link |
| `ui/demo/index.html` | New — demo page HTML |
| `ui/demo/app.js` | New — demo page JS |
| `ui/demo/styles.css` | New — demo page styles (extends compare shell tokens) |
| `scripts/ui/live_demo.py` | New — Python desktop app |
| `pyproject.toml` | Add matplotlib, librosa, PyAudio, pynvml to `[gpu]` extra |
| `tests/ui/test_demo_api.py` | New — API unit tests |
| `tests/ui/test_encode_artifact_path.py` | New — helper script tests |
