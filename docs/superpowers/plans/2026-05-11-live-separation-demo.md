# Live Separation Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the batch URL-encoding bug, add a `/api/separate` POST endpoint, build a browser demo page with per-stem waveform/spectrogram playback, and build a Python desktop app with animated matplotlib spectrogram panels + PyAudio dual-stream playback.

**Architecture:** The existing `serve_compare_demo.py` static server is upgraded with a `do_POST` handler; a new `ui/demo/` page drives the browser experience; a standalone `scripts/ui/live_demo.py` script powers the desktop demo. Shared audio-rendering functions are extracted into `ui/shared/audio-render.js` so both pages use identical code.

**Tech Stack:** Python 3.11, stdlib `cgi`/`wave`/`json`/`uuid`, UMX via `openunmix`, `matplotlib`, `librosa`, `PyAudio`, `pynvml` (optional); browser: vanilla ES modules, Canvas 2D, HTMLAudioElement.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `scripts/ui/__init__.py` | Create | Make scripts/ui importable as a package |
| `scripts/ui/encode_artifact_path.py` | Create | CLI helper: URL-encode artifact path for batch file |
| `run_local_demo.bat` | Modify | Replace broken for/f backtick with helper script call |
| `ui/shared/audio-render.js` | Create | Exported `readAscii`, `decodePcmWav`, `drawWaveform`, `drawSpectrogram` |
| `ui/compare/index.html` | Modify | Switch to `type="module"`, add "→ Live Demo" nav link |
| `ui/compare/app.js` | Modify | Import from shared module, remove duplicated functions |
| `scripts/ui/serve_compare_demo.py` | Modify | Add `do_POST` for `/api/separate`, `_SEPARATOR_CACHE`, `_run_separation`, `_send_json` |
| `ui/demo/index.html` | Create | Demo page HTML: upload form, waveform lanes, perf overlay, benchmark table |
| `ui/demo/styles.css` | Create | Demo-specific CSS (reuses compare shell CSS variables) |
| `ui/demo/app.js` | Create | Demo page JS: POST, stem rendering, per-lane playback, benchmark table |
| `scripts/ui/live_demo.py` | Create | Standalone desktop app: separation + matplotlib + PyAudio |
| `pyproject.toml` | Modify | Add `matplotlib`, `librosa`, `PyAudio`, `pynvml` to gpu extra; omit live_demo.py from coverage |
| `tests/ui/test_encode_artifact_path.py` | Create | Tests for encode_artifact_path helper |
| `tests/ui/test_demo_api.py` | Create | HTTP tests for POST /api/separate error paths |

---

## Task 1: URL-Encoding Helper + Batch File Fix

**Files:**
- Create: `scripts/ui/__init__.py`
- Create: `scripts/ui/encode_artifact_path.py`
- Create: `tests/ui/test_encode_artifact_path.py`
- Modify: `run_local_demo.bat`

- [ ] **Step 1.1: Create scripts/ui package init**

```bash
touch /path/to/repo/scripts/ui/__init__.py
```

File content: empty (zero bytes).

- [ ] **Step 1.2: Write failing tests**

Create `tests/ui/test_encode_artifact_path.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ui.encode_artifact_path import encode_artifact_path


def test_simple_relative_path(tmp_path):
    artifact = tmp_path / "artifacts" / "live" / "result.json"
    artifact.parent.mkdir(parents=True)
    artifact.touch()
    result = encode_artifact_path(str(tmp_path), str(artifact))
    assert result == "/artifacts/live/result.json"


def test_path_with_spaces(tmp_path):
    sub = tmp_path / "live results"
    sub.mkdir()
    artifact = sub / "data.json"
    artifact.touch()
    result = encode_artifact_path(str(tmp_path), str(artifact))
    assert result == "/live%20results/data.json"


def test_outside_repo_raises(tmp_path):
    other = tmp_path.parent / "other_dir_encode_test"
    with pytest.raises(ValueError):
        encode_artifact_path(str(tmp_path), str(other / "result.json"))


def test_starts_with_slash(tmp_path):
    artifact = tmp_path / "foo.json"
    artifact.touch()
    result = encode_artifact_path(str(tmp_path), str(artifact))
    assert result.startswith("/")
```

- [ ] **Step 1.3: Run tests — expect ImportError (module not yet created)**

```bash
pytest tests/ui/test_encode_artifact_path.py -v
```

Expected: `ImportError: cannot import name 'encode_artifact_path'` or `ModuleNotFoundError`.

- [ ] **Step 1.4: Create encode_artifact_path.py**

Create `scripts/ui/encode_artifact_path.py`:

```python
"""URL-encode an artifact path relative to a repo root for use in batch files.

Usage:
    python encode_artifact_path.py <repo-root> <artifact-path>

Prints the URL-encoded path (e.g. /artifacts/live/result.json) to stdout.
Exits 1 if the artifact is outside the repo root.
Exits 2 on wrong number of arguments.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote


def encode_artifact_path(root: str, artifact: str) -> str:
    """Return '/' + URL-encoded posix relative path from root to artifact.

    Raises ValueError if artifact is not inside root.
    """
    root_path = Path(root).resolve()
    artifact_path = Path(artifact).resolve()
    relative = artifact_path.relative_to(root_path)
    return "/" + quote(relative.as_posix(), safe="/")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <repo-root> <artifact-path>", file=sys.stderr)
        sys.exit(2)
    try:
        print(encode_artifact_path(sys.argv[1], sys.argv[2]))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 1.5: Run tests — expect all pass**

```bash
pytest tests/ui/test_encode_artifact_path.py -v
```

Expected: 4 PASSED.

- [ ] **Step 1.6: Fix run_local_demo.bat**

In `run_local_demo.bat`, find this block (around line 73):

```batch
for /f "usebackq delims=" %%I in (`"%VENV_PYTHON%" -c "from pathlib import Path; from urllib.parse import quote; import sys; root=Path(sys.argv[1]).resolve(); artifact=Path(sys.argv[2]).resolve(); print('/' + quote(artifact.relative_to(root).as_posix(), safe='/'))" "%PROJECT_ROOT%" "%ARTIFACT_PATH%"`) do set "ENCODED_ARTIFACT_PATH=%%I"
```

Replace it with:

```batch
for /f "usebackq delims=" %%I in (`"%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\ui\encode_artifact_path.py" "%PROJECT_ROOT%" "%ARTIFACT_PATH%"`) do set "ENCODED_ARTIFACT_PATH=%%I"
```

- [ ] **Step 1.7: Commit**

```bash
git add scripts/ui/__init__.py scripts/ui/encode_artifact_path.py \
        tests/ui/test_encode_artifact_path.py run_local_demo.bat
git commit -m "fix(batch): extract URL-encoding to helper script, fix artifact URL"
```

---

## Task 2: Shared Audio Rendering Module

**Files:**
- Create: `ui/shared/audio-render.js`
- Modify: `ui/compare/index.html`
- Modify: `ui/compare/app.js`

- [ ] **Step 2.1: Create ui/shared/audio-render.js**

Extract the three functions from `ui/compare/app.js` (lines 395–540) into a new file. The content is identical — just add `export` to each function definition and remove `readAscii` (keep it as a module-private helper):

Create `ui/shared/audio-render.js`:

```javascript
function readAscii(view, offset, length) {
  let text = '';
  for (let index = 0; index < length; index += 1) {
    text += String.fromCharCode(view.getUint8(offset + index));
  }
  return text;
}

export function decodePcmWav(buffer) {
  const view = new DataView(buffer);
  if (readAscii(view, 0, 4) !== 'RIFF' || readAscii(view, 8, 4) !== 'WAVE') {
    throw new Error('WAV file must use RIFF/WAVE format');
  }

  let offset = 12;
  let channels = 1;
  let bitsPerSample = 16;
  let dataOffset = -1;
  let dataSize = 0;
  while (offset + 8 <= view.byteLength) {
    const chunkId = readAscii(view, offset, 4);
    const chunkSize = view.getUint32(offset + 4, true);
    const payloadOffset = offset + 8;
    if (chunkId === 'fmt ') {
      const audioFormat = view.getUint16(payloadOffset, true);
      if (audioFormat !== 1) {
        throw new Error('Only PCM WAV files are supported');
      }
      channels = view.getUint16(payloadOffset + 2, true);
      bitsPerSample = view.getUint16(payloadOffset + 14, true);
    }
    if (chunkId === 'data') {
      dataOffset = payloadOffset;
      dataSize = chunkSize;
      break;
    }
    offset = payloadOffset + chunkSize + (chunkSize % 2);
  }

  if (dataOffset < 0 || bitsPerSample !== 16) {
    throw new Error('WAV file must contain 16-bit PCM data');
  }

  const sampleCount = Math.floor(dataSize / 2 / channels);
  const samples = new Float32Array(sampleCount);
  for (let frame = 0; frame < sampleCount; frame += 1) {
    let sum = 0;
    for (let channel = 0; channel < channels; channel += 1) {
      sum += view.getInt16(dataOffset + ((frame * channels + channel) * 2), true) / 32768;
    }
    samples[frame] = sum / channels;
  }
  return samples;
}

export function drawWaveform(canvas, samples) {
  const context = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  context.clearRect(0, 0, width, height);
  context.fillStyle = '#081523';
  context.fillRect(0, 0, width, height);
  context.strokeStyle = '#8ee3ff';
  context.lineWidth = 2;
  context.beginPath();
  const centerY = height / 2;
  for (let x = 0; x < width; x += 1) {
    const start = Math.floor((x / width) * samples.length);
    const end = Math.max(start + 1, Math.floor(((x + 1) / width) * samples.length));
    let min = 1;
    let max = -1;
    for (let index = start; index < end; index += 1) {
      const value = samples[index] || 0;
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
    context.moveTo(x, centerY - max * (height * 0.42));
    context.lineTo(x, centerY - min * (height * 0.42));
  }
  context.stroke();
  canvas.dataset.rendered = 'true';
}

export function drawSpectrogram(canvas, samples) {
  const W = canvas.width;
  const H = canvas.height;
  const N = 128;
  const numBins = N >> 1;
  const hop = Math.max(1, Math.floor(samples.length / W));
  const ctx = canvas.getContext('2d');
  const imageData = ctx.createImageData(W, H);

  const cosT = new Float32Array(numBins * N);
  const sinT = new Float32Array(numBins * N);
  for (let k = 0; k < numBins; k++) {
    for (let n = 0; n < N; n++) {
      const angle = (-2 * Math.PI * k * n) / N;
      cosT[k * N + n] = Math.cos(angle);
      sinT[k * N + n] = Math.sin(angle);
    }
  }

  const mag = new Float32Array(W * numBins);
  let peak = 1e-9;
  for (let col = 0; col < W; col++) {
    const base = col * hop;
    for (let k = 0; k < numBins; k++) {
      let re = 0, im = 0;
      const kt = k * N;
      for (let n = 0; n < N; n++) {
        const s = base + n < samples.length ? samples[base + n] : 0;
        const w = 0.5 * (1 - Math.cos((2 * Math.PI * n) / (N - 1)));
        const sw = s * w;
        re += sw * cosT[kt + n];
        im += sw * sinT[kt + n];
      }
      const m = Math.sqrt(re * re + im * im);
      mag[col * numBins + k] = m;
      if (m > peak) peak = m;
    }
  }

  const binH = H / numBins;
  for (let col = 0; col < W; col++) {
    for (let k = 0; k < numBins; k++) {
      const v = Math.pow(mag[col * numBins + k] / peak, 0.35);
      const r = v > 0.5 ? Math.round((v - 0.5) * 2 * 255) : 0;
      const g = Math.round(Math.min(v * 2, 1) * 200);
      const b = v < 0.5 ? Math.round((1 - v * 2) * 220) : 0;
      const rowTop = Math.round((numBins - 1 - k) * binH);
      const rowBot = Math.min(H, Math.round((numBins - k) * binH));
      for (let row = rowTop; row < rowBot; row++) {
        const i = (row * W + col) * 4;
        imageData.data[i]     = r;
        imageData.data[i + 1] = g;
        imageData.data[i + 2] = b;
        imageData.data[i + 3] = 255;
      }
    }
  }
  ctx.putImageData(imageData, 0, 0);
  canvas.dataset.rendered = 'true';
}
```

- [ ] **Step 2.2: Update ui/compare/index.html**

In `ui/compare/index.html`:

1. Change line 8 from:
```html
    <script defer src="./app.js"></script>
```
to:
```html
    <script type="module" src="./app.js"></script>
```

2. After `<header class="hero">` opening tag, add a nav link before the `<p class="eyebrow">` (use inline style — compare shell's CSS doesn't define nav-link):
```html
      <header class="hero">
        <a href="/ui/demo/" style="display:inline-block;margin-bottom:0.75rem;color:#8ee3ff;font-size:0.875rem;text-decoration:none;">→ Live Demo</a>
```

- [ ] **Step 2.3: Update ui/compare/app.js**

At the very top of `ui/compare/app.js`, add the import line:

```javascript
import { decodePcmWav, drawWaveform, drawSpectrogram } from '../shared/audio-render.js';
```

Then remove the four function bodies that are now in the shared module. In `ui/compare/app.js`, delete:
- The `function readAscii(view, offset, length)` block (lines ~395–402)
- The `function decodePcmWav(buffer)` block (lines ~404–448)
- The `function drawWaveform(canvas, samples)` block (lines ~450–476)
- The `function drawSpectrogram(canvas, samples)` block (lines ~478–540)

These are the exact functions whose implementations now live in `ui/shared/audio-render.js`. The import at line 1 replaces them.

- [ ] **Step 2.4: Run existing Playwright tests to verify no regressions**

```bash
pytest tests/ui/test_compare_ui.py -v
```

Expected: all tests PASS. If they fail with import errors, verify `type="module"` was set correctly in index.html and the shared module path is correct.

- [ ] **Step 2.5: Commit**

```bash
git add ui/shared/audio-render.js ui/compare/index.html ui/compare/app.js
git commit -m "refactor(ui): extract audio rendering to shared ES module"
```

---

## Task 3: Server POST Endpoint

**Files:**
- Create: `tests/ui/test_demo_api.py`
- Modify: `scripts/ui/serve_compare_demo.py`

- [ ] **Step 3.1: Write failing API tests**

Create `tests/ui/test_demo_api.py`:

```python
from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ui.serve_compare_demo import CompareDemoHandler


@pytest.fixture(scope="module")
def demo_server():
    tmpdir = tempfile.mkdtemp()
    handler = partial(CompareDemoHandler, directory=tmpdir)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield ("127.0.0.1", port)
    server.shutdown()


def _post(host, port, path, body, headers):
    conn = http.client.HTTPConnection(host, port, timeout=10)
    conn.request("POST", path, body, headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def test_post_missing_file(demo_server):
    host, port = demo_server
    body = (
        b"--boundary\r\n"
        b'Content-Disposition: form-data; name="device"\r\n\r\ngpu\r\n'
        b"--boundary--\r\n"
    )
    status, data = _post(host, port, "/api/separate", body, {
        "Content-Type": "multipart/form-data; boundary=boundary",
        "Content-Length": str(len(body)),
    })
    assert status == 400
    payload = json.loads(data)
    assert "error" in payload


def test_post_oversized(demo_server):
    host, port = demo_server
    status, data = _post(host, port, "/api/separate", b"x", {
        "Content-Type": "multipart/form-data; boundary=boundary",
        "Content-Length": str(51 * 1024 * 1024),
    })
    assert status == 413
    payload = json.loads(data)
    assert "error" in payload


def test_post_unknown_path(demo_server):
    host, port = demo_server
    status, data = _post(host, port, "/api/unknown", b"", {
        "Content-Type": "application/json",
        "Content-Length": "0",
    })
    assert status == 404


def test_post_response_is_json(demo_server):
    """Error responses from /api/separate must be valid JSON."""
    host, port = demo_server
    body = b"--b\r\nContent-Disposition: form-data; name=\"x\"\r\n\r\nval\r\n--b--\r\n"
    status, data = _post(host, port, "/api/separate", body, {
        "Content-Type": "multipart/form-data; boundary=b",
        "Content-Length": str(len(body)),
    })
    assert status in (400, 500)
    parsed = json.loads(data)
    assert isinstance(parsed, dict)
```

- [ ] **Step 3.2: Run tests — expect AttributeError (do_POST not yet defined)**

```bash
pytest tests/ui/test_demo_api.py -v
```

Expected: tests for 404 and oversized may pass unexpectedly or fail with connection errors; the missing-file test will fail because `do_POST` doesn't exist yet (server returns 501).

- [ ] **Step 3.3: Implement do_POST in serve_compare_demo.py**

Replace the full content of `scripts/ui/serve_compare_demo.py` with:

```python
from __future__ import annotations

import argparse
import cgi
import json
import sys
import tempfile
import uuid
import wave
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIRECTORY = PROJECT_ROOT
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

_SEPARATOR_CACHE: dict[str, Any] = {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def _run_separation(mp3_bytes: bytes, device_str: str, project_root: Path) -> dict[str, Any]:
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from live_runtime import umx_separator
    from live_runtime.mp3_ingest import decode_audio_to_pcm
    from live_runtime.stem_router import write_live_stems_from_arrays

    device = umx_separator.resolve_device(device_str)

    if device not in _SEPARATOR_CACHE:
        _SEPARATOR_CACHE[device] = umx_separator.load_umxhq_separator(device)
    separator = _SEPARATOR_CACHE[device]

    run_id = uuid.uuid4().hex[:8]
    output_dir = project_root / "artifacts" / "live" / f"demo-{run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    mp3_path = output_dir / "input.mp3"
    mp3_path.write_bytes(mp3_bytes)

    decoded = decode_audio_to_pcm(mp3_path, target_sample_rate_hz=44100, chunk_duration_s=0.5)

    audio_tensor = umx_separator.pcm_to_tensor(decoded.pcm)
    sep = umx_separator.separate_tensor(audio_tensor, decoded.sample_rate_hz, separator, device)

    mix_path = output_dir / "mix.wav"
    with wave.open(str(mix_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(decoded.sample_rate_hz)
        wf.writeframes(decoded.pcm)

    routing = write_live_stems_from_arrays(sep.stems, output_dir, sep.sample_rate_hz)

    device_used = "gpu" if device == "cuda" else device
    artifact_path = output_dir / "live_runtime_result.json"
    _write_json_atomic(artifact_path, {
        "status": "ok",
        "input": str(mp3_path),
        "timestamp": datetime.now(UTC).isoformat(),
        "stft_ms": sep.timings.stft_ms,
        "infer_ms": sep.timings.infer_ms,
        "istft_ms": sep.timings.istft_ms,
        "total_ms": sep.timings.total_ms,
        "device_used": device_used,
        "sample_rate_hz": sep.sample_rate_hz,
    })

    def rel(p: Path) -> str:
        return str(p.relative_to(project_root)).replace("\\", "/")

    return {
        "artifact_path": rel(artifact_path),
        "stem_urls": {
            "input":  rel(mix_path),
            "vocals": rel(Path(routing.vocals_path)),
            "drums":  rel(Path(routing.drums_path)),
            "bass":   rel(Path(routing.bass_path)),
            "other":  rel(Path(routing.other_path)),
        },
        "timings": {
            "stft_ms":  sep.timings.stft_ms,
            "infer_ms": sep.timings.infer_ms,
            "istft_ms": sep.timings.istft_ms,
            "total_ms": sep.timings.total_ms,
        },
        "device_used": device_used,
    }


class CompareDemoHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        message = format % args
        print(f"compare-demo: {self.client_address[0]} {message}", file=sys.stderr)

    def do_POST(self) -> None:
        if self.path != "/api/separate":
            self.send_error(404, "Not Found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > MAX_UPLOAD_BYTES:
            self._send_json(413, {"error": "File too large (max 50 MB)"})
            return

        environ = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": str(content_length),
        }
        try:
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=environ)
        except Exception as exc:
            self._send_json(400, {"error": f"Failed to parse request: {exc}"})
            return

        if "file" not in form:
            self._send_json(400, {"error": "Missing file field"})
            return

        file_item = form["file"]
        if not hasattr(file_item, "file") or file_item.file is None:
            self._send_json(400, {"error": "Missing file field"})
            return

        device_str = form.getvalue("device", "gpu") or "gpu"
        mp3_bytes = file_item.file.read()

        try:
            result = _run_separation(mp3_bytes, device_str, Path(self.directory))
            self._send_json(200, result)
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the compare UI from a local static root.")
    parser.add_argument("--bind", default=DEFAULT_BIND,
                        help=f"Interface to bind to (default: {DEFAULT_BIND})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Port to listen on (default: {DEFAULT_PORT})")
    parser.add_argument("--directory", default=str(DEFAULT_DIRECTORY),
                        help="Directory to serve (default: repository root)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    directory = Path(args.directory).resolve()

    if not directory.exists():
        print(f"compare-demo: directory not found: {directory}", file=sys.stderr)
        return 2
    if not directory.is_dir():
        print(f"compare-demo: directory is not a directory: {directory}", file=sys.stderr)
        return 2

    handler = partial(CompareDemoHandler, directory=str(directory))

    try:
        server = ThreadingHTTPServer((args.bind, args.port), handler)
    except OSError as exc:
        print(f"compare-demo: failed to bind {args.bind}:{args.port} — {exc}", file=sys.stderr)
        return 3

    host, port = server.server_address[:2]
    print(f"compare-demo: serving {directory} at http://{host}:{port}/ui/compare/", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("compare-demo: shutdown requested", file=sys.stderr)
    finally:
        server.server_close()
        print("compare-demo: stopped", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3.4: Run API tests — expect all pass**

```bash
pytest tests/ui/test_demo_api.py -v
```

Expected: 4 PASSED (`test_post_missing_file`, `test_post_oversized`, `test_post_unknown_path`, `test_post_response_is_json`).

- [ ] **Step 3.5: Also run the existing compare UI tests to confirm no regressions**

```bash
pytest tests/ui/ -v
```

Expected: all tests pass.

- [ ] **Step 3.6: Commit**

```bash
git add scripts/ui/serve_compare_demo.py tests/ui/test_demo_api.py
git commit -m "feat(server): add POST /api/separate endpoint with separator cache"
```

---

## Task 4: Web Demo Page HTML + CSS

**Files:**
- Create: `ui/demo/index.html`
- Create: `ui/demo/styles.css`

- [ ] **Step 4.1: Create ui/demo/index.html**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Live Separation Demo</title>
    <link rel="stylesheet" href="../compare/styles.css" />
    <link rel="stylesheet" href="./styles.css" />
    <script type="module" src="./app.js"></script>
  </head>
  <body>
    <main class="app-shell">
      <header class="hero">
        <a href="/ui/compare/" class="nav-back">← Compare shell</a>
        <p class="eyebrow">Live separation demo</p>
        <h1>MP3 → Separated Stems</h1>
        <p class="lede">
          Upload an audio file to run the full GPU separation pipeline and audition each isolated stem.
        </p>
      </header>

      <!-- Step 1: Upload -->
      <section class="controls card" aria-labelledby="upload-heading">
        <div class="section-heading">
          <h2 id="upload-heading">Step 1 — Upload</h2>
          <p>Choose an audio file and click Separate to run the pipeline.</p>
        </div>
        <div class="control-row">
          <label class="file-picker" for="mp3-file">
            <span class="file-picker-label">Audio file</span>
            <input id="mp3-file" name="mp3-file" type="file"
              accept="audio/mpeg,audio/wav,audio/mp4,audio/ogg,audio/flac,.mp3,.wav,.m4a,.ogg,.flac" />
          </label>
          <select id="device-select" class="device-select" aria-label="Processing device">
            <option value="gpu">GPU</option>
            <option value="cpu">CPU</option>
          </select>
          <button id="separate-btn" type="button" class="primary-button" disabled>Separate</button>
        </div>
        <p id="status-line" class="hint" data-testid="status-line">Awaiting file…</p>
      </section>

      <!-- Step 2: Waveform Lanes -->
      <section id="waveform-section" class="card waveform-panel" hidden
               aria-labelledby="waveform-heading">
        <div class="section-heading">
          <h2 id="waveform-heading">Step 2 — Waveform Lanes</h2>
          <p>Waveform and spectrogram for each separated stem. Click Play to audition.</p>
        </div>
        <div class="waveform-grid">
          <article class="waveform-lane demo-lane">
            <span class="lane-label">Input</span>
            <div class="lane-canvases">
              <canvas id="waveform-input" data-testid="waveform-canvas-input" width="640" height="96"></canvas>
              <canvas id="spectrogram-input" class="spectrogram-canvas" width="640" height="80"></canvas>
            </div>
            <button id="play-input" type="button" class="mode-button" disabled aria-pressed="false">Play</button>
          </article>
          <article class="waveform-lane demo-lane">
            <span class="lane-label">Vocals</span>
            <div class="lane-canvases">
              <canvas id="waveform-vocals" data-testid="waveform-canvas-vocals" width="640" height="96"></canvas>
              <canvas id="spectrogram-vocals" class="spectrogram-canvas" width="640" height="80"></canvas>
            </div>
            <button id="play-vocals" type="button" class="mode-button" disabled aria-pressed="false">Play</button>
          </article>
          <article class="waveform-lane demo-lane">
            <span class="lane-label">Drums</span>
            <div class="lane-canvases">
              <canvas id="waveform-drums" data-testid="waveform-canvas-drums" width="640" height="96"></canvas>
              <canvas id="spectrogram-drums" class="spectrogram-canvas" width="640" height="80"></canvas>
            </div>
            <button id="play-drums" type="button" class="mode-button" disabled aria-pressed="false">Play</button>
          </article>
          <article class="waveform-lane demo-lane">
            <span class="lane-label">Bass</span>
            <div class="lane-canvases">
              <canvas id="waveform-bass" data-testid="waveform-canvas-bass" width="640" height="96"></canvas>
              <canvas id="spectrogram-bass" class="spectrogram-canvas" width="640" height="80"></canvas>
            </div>
            <button id="play-bass" type="button" class="mode-button" disabled aria-pressed="false">Play</button>
          </article>
          <article class="waveform-lane demo-lane">
            <span class="lane-label">Other</span>
            <div class="lane-canvases">
              <canvas id="waveform-other" data-testid="waveform-canvas-other" width="640" height="96"></canvas>
              <canvas id="spectrogram-other" class="spectrogram-canvas" width="640" height="80"></canvas>
            </div>
            <button id="play-other" type="button" class="mode-button" disabled aria-pressed="false">Play</button>
          </article>
        </div>
      </section>

      <!-- Step 3: Performance Overlay -->
      <section id="perf-section" class="card panel" hidden aria-labelledby="perf-heading">
        <div class="section-heading">
          <h2 id="perf-heading">Step 3 — Performance</h2>
          <p>Stage timing from the separation run.</p>
        </div>
        <dl class="definition-list timing-grid">
          <div><dt>STFT</dt><dd id="timing-stft" data-testid="timing-stft">—</dd></div>
          <div><dt>Infer</dt><dd id="timing-infer" data-testid="timing-infer">—</dd></div>
          <div><dt>ISTFT</dt><dd id="timing-istft" data-testid="timing-istft">—</dd></div>
          <div><dt>Total</dt><dd id="timing-total" data-testid="timing-total">—</dd></div>
          <div><dt>Device</dt><dd id="device-used" data-testid="device-used">—</dd></div>
        </dl>
      </section>

      <!-- Step 4: Benchmark Table -->
      <section id="benchmark-section" class="card" hidden aria-labelledby="benchmark-heading">
        <div class="section-heading">
          <h2 id="benchmark-heading">Step 4 — GPU vs CPU Benchmark</h2>
          <p>Loaded from the capstone evidence manifest.</p>
        </div>
        <div id="benchmark-table-wrap" hidden>
          <table class="benchmark-table">
            <thead>
              <tr>
                <th>Backend</th>
                <th>Chunk (ms)</th>
                <th>Speedup</th>
                <th>SDR</th>
              </tr>
            </thead>
            <tbody id="benchmark-tbody"></tbody>
          </table>
        </div>
        <p id="benchmark-unavailable" class="hint">Benchmark data unavailable.</p>
      </section>

      <section id="banner-region" aria-live="polite" aria-atomic="true">
        <div id="error-banner" class="banner banner-error is-hidden" role="alert"
             data-testid="error-banner"></div>
      </section>
    </main>
  </body>
</html>
```

- [ ] **Step 4.2: Create ui/demo/styles.css**

```css
.nav-back {
  display: inline-block;
  margin-bottom: 1rem;
  color: var(--accent, #8ee3ff);
  text-decoration: none;
  font-size: 0.875rem;
}

.nav-back:hover {
  text-decoration: underline;
}

.nav-link {
  display: inline-block;
  color: var(--accent, #8ee3ff);
  text-decoration: none;
  font-size: 0.875rem;
  margin-bottom: 0.5rem;
}

.nav-link:hover {
  text-decoration: underline;
}

.device-select {
  padding: 0.5rem 0.75rem;
  background: var(--surface-2, #0e1f30);
  color: var(--text-primary, #e0f0ff);
  border: 1px solid var(--border, #1e3a5f);
  border-radius: 4px;
  font-size: 0.875rem;
  cursor: pointer;
}

.demo-lane {
  display: grid;
  grid-template-columns: 4.5rem 1fr auto;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--border, #1e3a5f);
}

.demo-lane:last-child {
  border-bottom: none;
}

.lane-label {
  font-size: 0.875rem;
  color: var(--text-secondary, #7fb3d3);
  font-weight: 600;
}

.benchmark-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.benchmark-table th,
.benchmark-table td {
  padding: 0.5rem 1rem;
  text-align: left;
  border-bottom: 1px solid var(--border, #1e3a5f);
}

.benchmark-table th {
  color: var(--text-secondary, #7fb3d3);
  font-weight: 600;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.benchmark-table tbody tr:last-child td {
  border-bottom: none;
}
```

- [ ] **Step 4.3: Commit**

```bash
git add ui/demo/index.html ui/demo/styles.css
git commit -m "feat(ui): add demo page HTML and CSS"
```

---

## Task 5: Web Demo Page JavaScript

**Files:**
- Create: `ui/demo/app.js`

- [ ] **Step 5.1: Create ui/demo/app.js**

```javascript
import { decodePcmWav, drawWaveform, drawSpectrogram } from '../shared/audio-render.js';

const STEMS = ['input', 'vocals', 'drums', 'bass', 'other'];

const el = {
  fileInput: document.getElementById('mp3-file'),
  deviceSelect: document.getElementById('device-select'),
  separateBtn: document.getElementById('separate-btn'),
  statusLine: document.getElementById('status-line'),
  errorBanner: document.getElementById('error-banner'),
  waveformSection: document.getElementById('waveform-section'),
  perfSection: document.getElementById('perf-section'),
  benchmarkSection: document.getElementById('benchmark-section'),
  timingStft: document.getElementById('timing-stft'),
  timingInfer: document.getElementById('timing-infer'),
  timingIstft: document.getElementById('timing-istft'),
  timingTotal: document.getElementById('timing-total'),
  deviceUsed: document.getElementById('device-used'),
  benchmarkTableWrap: document.getElementById('benchmark-table-wrap'),
  benchmarkTbody: document.getElementById('benchmark-tbody'),
  benchmarkUnavailable: document.getElementById('benchmark-unavailable'),
};

const lanes = Object.fromEntries(STEMS.map((stem) => [stem, {
  waveform: document.getElementById(`waveform-${stem}`),
  spectrogram: document.getElementById(`spectrogram-${stem}`),
  playBtn: document.getElementById(`play-${stem}`),
  audioSrc: null,
}]));

let playingStem = null;
let activeAudio = null;

function showError(message) {
  el.errorBanner.textContent = message;
  el.errorBanner.classList.remove('is-hidden');
  el.statusLine.textContent = 'Separation failed — see error above.';
}

function clearError() {
  el.errorBanner.textContent = '';
  el.errorBanner.classList.add('is-hidden');
}

async function runSeparation() {
  const file = el.fileInput.files?.[0];
  if (!file) return;

  clearError();
  el.separateBtn.disabled = true;
  const startMs = Date.now();
  const timer = setInterval(() => {
    el.statusLine.textContent = `Separating… ${((Date.now() - startMs) / 1000).toFixed(1)}s`;
  }, 100);

  try {
    const form = new FormData();
    form.append('file', file);
    form.append('device', el.deviceSelect.value);

    const resp = await fetch('/api/separate', { method: 'POST', body: form });
    const result = await resp.json();

    if (!resp.ok) {
      showError(`Separation failed: ${result.error ?? resp.statusText}`);
      return;
    }

    clearInterval(timer);
    el.statusLine.textContent = `Done in ${((Date.now() - startMs) / 1000).toFixed(1)}s`;

    await renderStems(result.stem_urls);
    renderPerf(result.timings, result.device_used);
    await loadBenchmarkTable();

    el.waveformSection.hidden = false;
    el.perfSection.hidden = false;
    el.benchmarkSection.hidden = false;
  } catch (err) {
    clearInterval(timer);
    showError(`Request failed: ${err.message}`);
  } finally {
    el.separateBtn.disabled = false;
  }
}

async function renderStems(stemUrls) {
  for (const stem of STEMS) {
    const url = stemUrls[stem];
    if (!url) continue;
    const resp = await fetch(url);
    const buffer = await resp.arrayBuffer();
    const samples = decodePcmWav(buffer);
    drawWaveform(lanes[stem].waveform, samples);
    drawSpectrogram(lanes[stem].spectrogram, samples);
    lanes[stem].audioSrc = url;
    lanes[stem].playBtn.disabled = false;
  }
}

function renderPerf(timings, deviceUsed) {
  el.timingStft.textContent = `${timings.stft_ms.toFixed(2)} ms`;
  el.timingInfer.textContent = `${timings.infer_ms.toFixed(2)} ms`;
  el.timingIstft.textContent = `${timings.istft_ms.toFixed(2)} ms`;
  el.timingTotal.textContent = `${timings.total_ms.toFixed(2)} ms`;
  el.deviceUsed.textContent = deviceUsed;
}

async function loadBenchmarkTable() {
  try {
    const resp = await fetch('/artifacts/bench/capstone_evidence_manifest.json', { cache: 'no-store' });
    if (!resp.ok) throw new Error('not found');
    renderBenchmarkTable(await resp.json());
  } catch {
    el.benchmarkUnavailable.hidden = false;
    el.benchmarkTableWrap.hidden = true;
  }
}

function renderBenchmarkTable(manifest) {
  const phases = Array.isArray(manifest.phases) ? manifest.phases : [manifest];
  el.benchmarkTbody.innerHTML = '';

  let cpuMs = null;
  const rows = [];

  for (const phase of phases) {
    const summary = (phase.summary && typeof phase.summary === 'object') ? phase.summary : phase;
    const kind = summary.execution_kind || phase.execution_kind;
    const ms = typeof summary.wall_clock_ms_per_chunk === 'number' ? summary.wall_clock_ms_per_chunk : null;
    const sdr = typeof summary.sdr_score === 'number' ? summary.sdr_score.toFixed(2) : '—';
    if (!kind || ms === null) continue;
    if (kind === 'cpu') cpuMs = ms;
    rows.push({ kind, ms, sdr });
  }

  for (const row of rows) {
    const speedup = (row.kind === 'cpu' || cpuMs === null)
      ? '1.0×'
      : `${(cpuMs / row.ms).toFixed(1)}×`;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${row.kind}</td>
      <td>${row.ms.toFixed(2)}</td>
      <td>${speedup}</td>
      <td>${row.sdr}</td>
    `;
    el.benchmarkTbody.appendChild(tr);
  }

  if (rows.length > 0) {
    el.benchmarkTableWrap.hidden = false;
    el.benchmarkUnavailable.hidden = true;
  }
}

function setupPlayButtons() {
  for (const stem of STEMS) {
    lanes[stem].playBtn.addEventListener('click', () => {
      const src = lanes[stem].audioSrc;
      if (!src) return;

      if (activeAudio) {
        activeAudio.pause();
        activeAudio = null;
        const prev = playingStem;
        playingStem = null;
        if (prev) {
          lanes[prev].playBtn.textContent = 'Play';
          lanes[prev].playBtn.setAttribute('aria-pressed', 'false');
        }
        if (prev === stem) return;
      }

      playingStem = stem;
      activeAudio = new Audio(src);
      lanes[stem].playBtn.textContent = 'Pause';
      lanes[stem].playBtn.setAttribute('aria-pressed', 'true');

      activeAudio.addEventListener('ended', () => {
        lanes[stem].playBtn.textContent = 'Play';
        lanes[stem].playBtn.setAttribute('aria-pressed', 'false');
        playingStem = null;
        activeAudio = null;
      });

      activeAudio.play().catch((err) => {
        showError(`Playback failed: ${err.message}`);
        lanes[stem].playBtn.textContent = 'Play';
        lanes[stem].playBtn.setAttribute('aria-pressed', 'false');
        playingStem = null;
        activeAudio = null;
      });
    });
  }
}

function initialize() {
  el.fileInput.addEventListener('change', () => {
    const file = el.fileInput.files?.[0];
    el.separateBtn.disabled = !file;
    el.statusLine.textContent = file ? `Selected: ${file.name}` : 'Awaiting file…';
  });
  el.separateBtn.addEventListener('click', runSeparation);
  setupPlayButtons();
}

initialize();
```

- [ ] **Step 5.2: Open http://127.0.0.1:8000/ui/demo/ in a browser and verify the page loads**

```bash
# In WSL terminal:
python scripts/ui/serve_compare_demo.py
```

Open `http://127.0.0.1:8000/ui/demo/` — the page should show the upload form with a disabled Separate button. The "← Compare shell" link should navigate to `/ui/compare/`.

- [ ] **Step 5.3: Verify nav link exists in compare shell**

Open `http://127.0.0.1:8000/ui/compare/` — confirm "→ Live Demo" link is visible in the header.

- [ ] **Step 5.4: Commit**

```bash
git add ui/demo/app.js
git commit -m "feat(ui): add demo page JS with upload, stem playback, perf overlay, benchmark table"
```

---

## Task 6: Python Desktop App + Dependency Updates

**Files:**
- Modify: `pyproject.toml`
- Create: `scripts/ui/live_demo.py`

- [ ] **Step 6.1: Update pyproject.toml**

In `pyproject.toml`, change the `gpu` extra to:

```toml
gpu = [
  "torch>=2.0.0",
  "torchaudio>=2.0.0",
  "openunmix>=1.2.1",
  "demucs==4.0.1",
  "matplotlib>=3.8",
  "librosa>=0.10",
  "PyAudio>=0.2.14",
  "pynvml>=11.0",
]
```

Also add `scripts/ui/live_demo.py` to the coverage omit list:

```toml
[tool.coverage.run]
omit = [
  "live_runtime/umx_separator.py",
  "scripts/benchmark/run_live_throughput.py",
  "scripts/benchmark/run_mic_latency.py",
  "scripts/eval/aggregate_metrics.py",
  "scripts/eval/run_demucs_eval.py",
  "scripts/eval/run_umx_eval.py",
  "scripts/export/export_umx_onnx.py",
  "scripts/ui/live_demo.py",
]
```

- [ ] **Step 6.2: Create scripts/ui/live_demo.py**

```python
"""Live separation demo: matplotlib 3-panel animated spectrogram + PyAudio playback.

Usage:
    python scripts/ui/live_demo.py --input song.mp3 [--device gpu|cpu] [--mic]
"""
from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _check_deps() -> None:
    missing = []
    for pkg in ("matplotlib", "librosa", "pyaudio"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print(f"Install with: pip install -e '.[gpu]'")
        sys.exit(1)


def _try_pynvml() -> Any:
    try:
        import pynvml  # type: ignore[import]
        pynvml.nvmlInit()
        return pynvml
    except Exception:
        return None


def _separate(input_path: Path, device_str: str):  # type: ignore[return]
    from live_runtime import umx_separator
    from live_runtime.mp3_ingest import decode_audio_to_pcm

    print(f"Separating {input_path.name} on {device_str}…")
    device = umx_separator.resolve_device(device_str)
    separator = umx_separator.load_umxhq_separator(device)
    decoded = decode_audio_to_pcm(input_path, target_sample_rate_hz=44100, chunk_duration_s=0.5)
    audio_tensor = umx_separator.pcm_to_tensor(decoded.pcm)
    result = umx_separator.separate_tensor(audio_tensor, decoded.sample_rate_hz, separator, device)
    print(f"  Done in {result.timings.total_ms:.0f} ms  (infer: {result.timings.infer_ms:.0f} ms)")
    return result.stems, result.sample_rate_hz, result.timings


def _stem_mono(arr) -> "np.ndarray":  # type: ignore[return]
    import numpy as np
    if arr.ndim == 2:
        return arr.mean(axis=0)
    return arr.astype(np.float32)


def run_demo(input_path: Path, device_str: str = "gpu", mic: bool = False) -> None:
    _check_deps()

    import tempfile
    import numpy as np
    import matplotlib.pyplot as plt
    import matplotlib.animation as animation
    import librosa  # type: ignore[import]
    import pyaudio  # type: ignore[import]

    nvml = _try_pynvml()

    # ── Capture from mic if requested ──────────────────────────────────────
    if mic:
        try:
            import sounddevice as sd  # type: ignore[import]
        except ImportError:
            print("Mic mode requires sounddevice: pip install sounddevice")
            sys.exit(1)
        sr_mic = 44100
        duration = 5
        print(f"Recording {duration}s from microphone…")
        recording = sd.rec(int(duration * sr_mic), samplerate=sr_mic, channels=1, dtype="int16")
        sd.wait()
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr_mic)
            wf.writeframes(recording.tobytes())
        input_path = Path(tmp.name)

    # ── Separation ──────────────────────────────────────────────────────────
    stems, sr, timings = _separate(input_path, device_str)

    vocal = _stem_mono(stems["vocals"])
    bass = _stem_mono(stems["bass"])
    drums = _stem_mono(stems["drums"])
    other = _stem_mono(stems["other"])
    mix = vocal + bass + drums + other

    # Normalize
    peak = float(np.abs(mix).max())
    if peak > 1e-9:
        mix = mix / peak
        vocal = vocal / peak

    # ── Pre-compute spectrograms ────────────────────────────────────────────
    print("Computing spectrograms…")
    n_fft, hop = 1024, 256
    mix_S = np.abs(librosa.stft(mix.astype(np.float32), n_fft=n_fft, hop_length=hop))
    voc_S = np.abs(librosa.stft(vocal.astype(np.float32), n_fft=n_fft, hop_length=hop))
    mask = np.clip(voc_S / (mix_S + 1e-7), 0.0, 1.0)

    to_db = lambda S: librosa.amplitude_to_db(S, ref=np.max)
    mix_db = to_db(mix_S)
    voc_db = to_db(voc_S)
    duration_s = mix_S.shape[1] * hop / sr

    # ── PyAudio streams ─────────────────────────────────────────────────────
    pa = pyaudio.PyAudio()

    def _pcm(arr: "np.ndarray") -> bytes:
        return (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

    instrumental = bass + drums + other
    inst_peak = float(np.abs(instrumental).max())
    if inst_peak > 1e-9:
        instrumental = instrumental / inst_peak

    voc_pcm = _pcm(vocal)
    inst_pcm = _pcm(instrumental)

    pos_v: list[int] = [0]
    pos_i: list[int] = [0]
    chunk = 1024

    def _voc_cb(in_data, frame_count, time_info, status):
        s, e = pos_v[0] * 2, (pos_v[0] + frame_count) * 2
        data = voc_pcm[s:e]
        if len(data) < frame_count * 2:
            data += b"\x00" * (frame_count * 2 - len(data))
        pos_v[0] += frame_count
        return data, pyaudio.paContinue

    def _inst_cb(in_data, frame_count, time_info, status):
        s, e = pos_i[0] * 2, (pos_i[0] + frame_count) * 2
        data = inst_pcm[s:e]
        if len(data) < frame_count * 2:
            data += b"\x00" * (frame_count * 2 - len(data))
        pos_i[0] += frame_count
        return data, pyaudio.paContinue

    stream_v = pa.open(format=pyaudio.paInt16, channels=1, rate=sr, output=True,
                       frames_per_buffer=chunk, stream_callback=_voc_cb)
    stream_i = pa.open(format=pyaudio.paInt16, channels=1, rate=sr, output=True,
                       frames_per_buffer=chunk, stream_callback=_inst_cb)

    # ── Matplotlib figure ───────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    fig.suptitle(f"Live Separation Demo — {input_path.name}", fontsize=13)

    extent = [0, duration_s, 0, sr / 2 / 1000]  # kHz on y
    kw = dict(aspect="auto", origin="lower", extent=extent)

    axes[0].imshow(mix_db, cmap="magma", **kw)
    axes[0].set_title("Input Mix Spectrogram")
    axes[0].set_ylabel("Freq (kHz)")

    axes[1].imshow(mask, cmap="viridis", vmin=0, vmax=1, **kw)
    axes[1].set_title("Predicted Vocal Mask")
    axes[1].set_ylabel("Freq (kHz)")

    axes[2].imshow(voc_db, cmap="magma", **kw)
    axes[2].set_title("Separated Vocal Output")
    axes[2].set_ylabel("Freq (kHz)")
    axes[2].set_xlabel("Time (s)")

    cursors = [ax.axvline(0.0, color="cyan", linewidth=1.5, alpha=0.8) for ax in axes]
    perf = fig.text(
        0.01, 0.005,
        f"Infer: {timings.infer_ms:.0f} ms | STFT: {timings.stft_ms:.0f} ms | GPU: init",
        fontsize=9, color="white",
        bbox=dict(facecolor="black", alpha=0.6),
    )
    plt.tight_layout(rect=[0, 0.04, 1, 0.96])

    def _gpu_pct() -> str:
        if nvml is None:
            return "N/A"
        try:
            h = nvml.nvmlDeviceGetHandleByIndex(0)
            u = nvml.nvmlDeviceGetUtilizationRates(h)
            return f"{u.gpu}%"
        except Exception:
            return "N/A"

    t0 = time.perf_counter()

    def _update(frame: int):
        elapsed = time.perf_counter() - t0
        for c in cursors:
            c.set_xdata([elapsed, elapsed])
        perf.set_text(
            f"Infer: {timings.infer_ms:.0f} ms | STFT: {timings.stft_ms:.0f} ms | GPU: {_gpu_pct()}"
        )
        return [*cursors, perf]

    ani = animation.FuncAnimation(  # noqa: F841
        fig, _update, interval=50, blit=True, cache_frame_data=False
    )

    stream_v.start_stream()
    stream_i.start_stream()
    print("Playing back — close the window to stop.")
    plt.show()

    for s in (stream_v, stream_i):
        s.stop_stream()
        s.close()
    pa.terminate()
    if nvml is not None:
        try:
            nvml.nvmlShutdown()
        except Exception:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live separation demo — matplotlib spectrogram + PyAudio.")
    parser.add_argument("--input", type=Path, default=None,
                        help="Input audio file. Defaults to fixtures/audio/demo_mix.mp3")
    parser.add_argument("--device", choices=["gpu", "cpu"], default="gpu")
    parser.add_argument("--mic", action="store_true", help="Capture 5s from mic instead of file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.mic and args.input is None:
        args.input = PROJECT_ROOT / "fixtures" / "audio" / "demo_mix.mp3"

    if not args.mic and not args.input.exists():
        print(f"Input not found: {args.input}")
        print("Provide --input <path> or use --mic for microphone capture.")
        return 1

    run_demo(args.input or Path(""), args.device, args.mic)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6.3: Run full test suite to verify no regressions and coverage is ≥ 80%**

```bash
pytest --cov=live_runtime --cov=scripts -v 2>&1 | tail -30
```

Expected: all tests pass, coverage ≥ 80%.

If coverage drops below 80% due to the new server code, add targeted assertions to `test_demo_api.py` to cover the `_send_json` helper and the `_write_json_atomic` function paths. The `_run_separation` function itself is intentionally not unit-tested (requires real GPU model).

- [ ] **Step 6.4: Commit**

```bash
git add pyproject.toml scripts/ui/live_demo.py
git commit -m "feat(desktop): add live_demo.py matplotlib spectrogram + PyAudio demo app"
```

---

## Task 7: End-to-End Smoke Test

*Manual verification — no automated test required.*

- [ ] **Step 7.1: Start the server**

```bash
# Windows (from project root):
.\run_local_demo.bat --mode smoke
```

Verify the terminal shows `run_local_demo: starting compare UI at http://127.0.0.1:8000/ui/compare/?artifact=artifacts/live/one-click/live_runtime_result.json` — the `?artifact=` must NOT be empty.

- [ ] **Step 7.2: Verify demo page**

Open `http://127.0.0.1:8000/ui/demo/` — confirm:
- Upload form is visible, Separate button is disabled
- "← Compare shell" link navigates to `/ui/compare/`

- [ ] **Step 7.3: Run GPU separation via the UI**

Upload any MP3 and click Separate (GPU). Confirm:
- Status line shows elapsed time during separation
- On success: 5 waveform + spectrogram lanes appear
- Each Play button plays the corresponding stem audio
- Performance section shows real infer_ms (> 100ms for a real GPU run)
- Benchmark table appears (or "Benchmark data unavailable" if no manifest)

- [ ] **Step 7.4: Run the desktop app**

```bash
# In WSL terminal:
python scripts/ui/live_demo.py --input fixtures/audio/demo_mix.mp3 --device gpu
```

Confirm:
- Terminal prints separation timing
- matplotlib window opens with 3 panels
- Audio plays (vocals in one stream, instrumental in another)
- Cursor line moves across all 3 panels in sync

- [ ] **Step 7.5: Final commit**

```bash
git add -A
git commit -m "chore: complete live separation demo — UI, desktop app, batch fix"
```
