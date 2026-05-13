# Compare UI — Frontend Documentation

The compare UI is a single-page, zero-dependency vanilla JS interface for inspecting persisted `live_runtime_result.json` artifacts. It runs entirely in the browser with no build step and serves data from `artifacts/` over a local HTTP server.

## Audience shell and launcher wiring

`/ui/compare/` is the canonical surface: **Upload separation** (`POST /api/separate` → redirect to `?artifact=…`), **query preload** (`artifact`, optional `artifact2` for CPU/GPU stem lanes, optional `benchmark`), and **Manual loaders** tucked under a `<details>` block (hidden when the page boots in preloaded audience mode). [`launch.py`](../../launch.py) adds `benchmark=` to opened URLs when `artifacts/bench/capstone_evidence_manifest.json` exists and passes `--benchmark` into [`scripts/ui/serve_compare_demo.py`](../../scripts/ui/serve_compare_demo.py). [`ui/demo/index.html`](../../ui/demo/index.html) redirects to `/ui/compare/`.

**Server and browser audio:** The live runtime writes **RIFF WAVE, 16-bit PCM, mono** (see `live_runtime/stem_router.py`). Successful CLI/API runs also emit **`mix.wav`** next to the four stems (`write_live_mix_wav`); the UI uses it for the Input lane when JSON `input` is not already a `.wav`. The browser decodes stems/mix via [`ui/shared/audio-render.js`](../../ui/shared/audio-render.js).

**Debugging “WAV file must use RIFF/WAVE format”:** Usually means `fetch` returned non-WAV bytes (HTML error, 404, JSON). Paths in artifacts must normalize to **root-absolute** URLs (`/artifacts/...`) so requests from `/ui/compare/` hit the repo root the demo server exposes. Hard-refresh if an old script was cached.

**Product scope:** This pipeline outputs **stem WAVs** (plus optional **`mix.wav`**), not a separated video file.

## Files

| File | Role |
|---|---|
| `ui/compare/index.html` | Page structure and semantic markup |
| `ui/compare/app.js` | All application logic — state, validation, rendering |
| `ui/compare/styles.css` | Dark-theme design system, responsive layout |
| `scripts/ui/serve_compare_demo.py` | Static HTTP server for local development |

---

## 1. Page Structure

`index.html` is organized into a `<main class="app-shell">` wrapper that contains five distinct regions rendered top-to-bottom:

### 1.1 Hero header (`.hero`)

```html
<header class="hero">
  <p class="eyebrow">Live runtime compare shell</p>
  <h1>Persisted artifact compare</h1>
  <p class="lede">…</p>
</header>
```

Static copy describing the tool. No JS interaction.

### 1.2 Artifact loader (`.controls.card`)

```html
<section class="controls card" aria-labelledby="controls-heading">
  <input id="artifact-file" type="file" accept="application/json,.json" />
  <button id="load-button" type="button">Load artifact</button>
  <p id="selected-file">No file selected</p>
</section>
```

Contains the file picker and load button. The `#selected-file` paragraph updates on `change`. The `#load-button` triggers the full parse-and-render pipeline. A `#file-hint` paragraph documents expected JSON shape.

### 1.3 Live feedback banners (`#banner-region`)

```html
<section id="banner-region" aria-live="polite" aria-atomic="true">
  <div id="error-banner" class="banner banner-error is-hidden" role="alert">…</div>
  <div id="status-banner" class="banner banner-status" role="status">…</div>
</section>
```

Two mutually exclusive banners. The error banner is hidden (`.is-hidden`) until an error occurs; the status banner is always visible. Both use ARIA live-region attributes for screen-reader announcements.

### 1.4 Compare toolbar (`.compare-toolbar.card`)

```html
<section class="compare-toolbar card" aria-labelledby="compare-heading">
  <div class="mode-switcher" role="tablist">
    <button data-mode="side-by-side" …>Side-by-side</button>
    <button data-mode="overlay" …>Overlay</button>
    <button data-mode="timeline" …>Timeline / sequence</button>
  </div>
  <dl class="compare-metrics">…</dl>
</section>
```

Three mode-toggle buttons (acting as a tab list). A `<dl>` grid reflects the active mode label, description, compare token, and runtime health state. Health state values (`healthy`/`degraded`/`fallback`) are written to `data-state` attributes and styled with color via CSS attribute selectors.

### 1.5 Compare canvas (`#compare-canvas`)

```html
<section class="card compare-canvas" data-mode="side-by-side" data-has-artifact="false">
  <div id="stage-board">…</div>
  <section class="final-stems-strip">…</section>
</section>
```

`#stage-board` is fully replaced by JS on each render. It holds either an empty-state placeholder or a mode-specific stage shell (`compare-stage-shell--side-by-side`, `--overlay`, or `--timeline`). The `data-mode` and `data-has-artifact` attributes on the section root expose render state to CSS and tests.

### 1.6 Runtime summary panels (`.grid`)

```html
<section class="grid">
  <article data-testid="source-panel">…</article>
  <article data-testid="health-panel">…</article>
  <article data-testid="timing-panel">…</article>
  <article data-testid="stem-panel">…</article>
  <article class="panel-wide" data-testid="provenance-panel">…</article>
</section>
```

Five `<article>` cards laid out in a two-column CSS grid. Each `<dd>` element has a stable `id` and `data-testid` that JS writes into directly via `textContent`. The provenance panel spans both columns (`.panel-wide`) and also contains the `#stages-list` rendered by `renderStages()`.

---

## 2. JavaScript Module (`app.js`)

The page loads `app.js` as an **`import`** module (`<script type="module">`) and **`../shared/audio-render.js`** for PCM WAV decoding and canvas draws.

Application logic stays in module scope (no ES classes).

### 2.1 Constants

| Name | Type | Purpose |
|---|---|---|
| `MODE_CONFIG` | `object` | Maps mode key → `{title, description}`. Single source of truth for mode labels (single-artifact layouts). |
| `STAGE_NOTES` | `object` | Maps lowercase stage name → human description shown on each stage card. |
| `elements` | `object` | Cached DOM references populated at parse time. |
| `compareState` | `object` | Mutable singleton holding artifact(s), benchmark state, per-lane playback URLs (`laneUrls`), `audioElement`, `activeMode`, etc. |
| `emptyState` | `object` | Frozen template of dash placeholders (`'—'`) for every field; used by `setEmptyState()`. |

`window.__compareState`, `window.__setCompareMode`, and `window.__loadCompareArtifact` are intentionally exposed for Playwright tests.

### 2.2 Audio preload, waveform lanes, and playback

Browser behavior lives in [`ui/compare/app.js`](../../ui/compare/app.js):

| Concern | Behavior |
|---|---|
| Serving | `scripts/ui/serve_compare_demo.py` serves the repo root so `fetch('/artifacts/live/…')` works from `/ui/compare/`. |
| Query preload | `?artifact=/artifacts/…/live_runtime_result.json` fetches JSON; optional `artifact2` loads a dual CPU/GPU timing compare; optional `benchmark` fetches benchmark JSON. Audience mode hides heavy manual loaders by default. |
| Stem canvases | `autoLoadStemWaveformsFromArtifact` fetches each `stem_paths` WAV, runs `decodePcmWav` (`ui/shared/audio-render.js`), draws waveform + spectrogram, and registers same-origin URLs for **lane playback**. Dual URL mode loads **stem** canvases (and stem **Play** targets) from the **secondary (GPU/accelerated) artifact**. |
| Input lane (`mix.wav`) | If JSON `input` ends with `.wav`, that asset is fetched. Otherwise `mix.wav` beside the stems is used (successful `run_live_separation.py` writes it). If PCM fetch fails, the UI may register **playback-only** URL for common container extensions on the provenance input path (.mp3, .m4a, .mp4, etc.)—Input waveform/spectrogram stay blank until a PCM WAV succeeds. |
| Lane playback | Each lane has a **Play** / **Pause** control (`data-testid="lane-play-<lane>"`). Only one lane plays at a time. **Play input** toggles the Input lane only; stem buttons play the fetched stem WAVs. |

**Dual `artifact2` policy:** Panels + summary timing derive from **`compareState.artifact`** (primary, typically CPU from the launcher URL order). Stem waveforms **and stem playback URLs** in the shared lanes use **`artifact2`** (GPU). Input lane playback follows the primary `mix.wav` / input heuristic so it matches the CPU (primary) run’s decoded mix.

Compare mode toggles (**Side-by-side / Overlay / Timeline**) rearrange **pipeline stage showcase** cards—not the waveform strip.

### Core UI function table

| Function | Signature | Purpose | DOM side-effects |
|---|---|---|---|
| `initialize` | `() → void` | Entry point. Calls `setEmptyState`, attaches listeners **including waveform / upload harness**, invokes **`initFromLocation()`**. | Listener wiring plus URL preload bootstrap. |
| `setBanner` | `(message, {type?}) → void` | Updates the live feedback banners. `type='error'` shows the error banner and hides status; default shows status banner. | Writes `textContent` on `#error-banner` / `#status-banner`. Toggles `.is-hidden` on error banner. |
| `setLoading` | `(isLoading) → void` | Disables/enables the load button and changes its label during async file read. | `loadButton.disabled`, `loadButton.textContent`. |
| `setText` | `(node, value) → void` | Thin wrapper around `node.textContent = value`. | `textContent` on any element. |
| `setStateValue` | `(node, value) → void` | Calls `setText`, then conditionally sets `node.dataset.state` to `healthy`/`degraded`/`fallback` or removes it. | `textContent` + `dataset.state`. |
| `setEmptyState` | `() → void` | Resets every panel field to `'—'` using `emptyState`. Calls `renderStages(['—'])` and `renderCompareCanvas(null)`. | All `<dd>` fields, stage list, canvas. |
| `handleFileSelection` | `() → void` | Updates `#selected-file` to reflect the currently chosen filename (or "No file selected"). | `selectedFile.textContent`. |
| `loadArtifactFromFile` | `async () → void` | Reads `fileInput.files[0]` with `File.text()`, JSON-parses, calls `normalizeArtifact`, then `renderArtifact`. On failure calls `setBanner` with the error message. | Calls `setLoading`, `setEmptyState`, `renderArtifact`, `setBanner`. |
| `normalizeArtifact` | `(payload, loadedPath) → artifact` | Validates raw JSON payload using all `expect*` helpers. Extracts and normalizes every field into a typed internal `artifact` object. Throws on any schema violation. | None (pure). |
| `renderArtifact` | `(artifact) → void` | Writes the normalized artifact into all panel `<dd>` elements. Updates `compareState.artifact`. Calls `renderStages`, `renderCompareCanvas`, `syncModeButtons`. | All panel fields, `compareState`. |
| `renderCompareCanvas` | `(artifact \| null) → void` | Rebuilds `#stage-board` for the current `compareState.activeMode`. Shows empty state when `artifact` is null. Calls one of `buildStageGrid`, `buildOverlayStageStack`, or `buildTimelineStageList`. | `#stage-board` innerHTML, `#compare-canvas` data attributes, final-stems copy. |
| `renderStages` | `(stages, stageTimings?) → void` | Rebuilds `#stages-list` in the provenance panel. Each `<li>` shows a stage pill, the stage name, and timing (or "Timing unavailable"). | `stagesList.innerHTML`. |
| `syncModeButtons` | `() → void` | Iterates `.mode-button` elements and toggles `.is-active` + `aria-pressed`/`aria-selected` to match `compareState.activeMode`. | `classList`, ARIA attributes on mode buttons. |
| `setCompareMode` | `(nextMode) → void` | Updates `compareState.activeMode`, re-renders the canvas and toolbar metrics. Falls back to `side-by-side` for unknown modes and shows an error banner. | `compareState.activeMode`, canvas, toolbar `<dd>`s, mode button states. |
| `buildStageCard` | `(stageDetail, {compact?}) → HTMLElement` | Creates a single `<article class="stage-card">` with index badge, stage name, note text, and timing pill. | None (returns element). |
| `buildStageGrid` | `(stages) → HTMLElement` | Returns a `<div class="compare-stage-grid">` containing one card per stage (side-by-side layout). | None (returns element). |
| `buildOverlayStageStack` | `(stages) → HTMLElement` | Returns a `<div class="compare-stage-stack">` with CSS custom properties `--overlay-offset` and `--overlay-scale` applied per card for a stacked-depth effect. | None (returns element). |
| `buildTimelineStageList` | `(stages) → HTMLElement` | Returns an `<ol class="compare-stage-timeline">`. Each `<li>` includes a `.timeline-rail` decorative connector and a stage card rendered in compact mode. | None (returns element). |

### 2.3 Validation helpers (all pure, all throw on failure)

| Function | Validates |
|---|---|
| `expectObject(value, path)` | Value is a non-null, non-array object. |
| `expectString(value, path)` | Value is a non-empty string. |
| `expectNumber(value, path)` | Value is a finite number. |
| `expectInteger(value, path, {min?})` | Value is an integer, optionally ≥ `min`. |
| `expectBoolean(value, path)` | Value is a boolean. |
| `normalizeStageTimings(source, stages)` | Accepts array (index-aligned with stages), object (keyed by stage name), or null. Throws on bad types. |
| `normalizeStemPaths(stemPaths)` | Requires exactly `{vocals, drums, bass, other}` — no extra keys, no missing keys. |
| `deriveSourceLabel(sourceKind, sourceMetadata)` | Returns explicit `source_label`/`sourceLabel` from metadata, or derives from source kind. |
| `buildStageDetails(stages, stageTimings)` | Maps stage names to `{index, stage, timing, note}` objects for `artifact.compare.stageDetails`. |
| `toDisplayText(value, formatter?)` | Returns `'—'` for null/undefined/empty, otherwise applies the formatter. |

---

## 3. Event Flow

### 3.1 Page load

```
initialize()
  └─ initFromLocation()                           → parses ?artifact=[&artifact2=][&benchmark=]
       ├─ preload paths present → fetch JSON, render artifact(s), benchmark silent fetch
       ├─ autoLoadStemWaveformsFromArtifact
       └─ finishPreloadExtras(...)               → benchmark + Input auto-load (+ mix.wav heuristic)
```

### 3.2 File selection

```
User clicks file input → OS file picker
  └─ 'change' event → handleFileSelection()
       └─ #selected-file.textContent = 'Selected file: <name>'  (or 'No file selected')
```

### 3.3 Artifact load

```
User clicks 'Load artifact'
  └─ 'click' event → loadArtifactFromFile()
       ├─ setLoading(true)           → disables button, shows 'Loading…'
       ├─ file.text()                → reads File as UTF-8 string
       ├─ JSON.parse(raw)            → throws SyntaxError on malformed JSON
       ├─ normalizeArtifact(payload, file.name)
       │    ├─ expectObject / expectString / expectNumber / expectInteger / expectBoolean
       │    ├─ normalizeStemPaths    → validates 4-key stem_paths object
       │    ├─ normalizeStageTimings → handles array or object timings
       │    ├─ deriveSourceLabel     → picks or derives human source label
       │    ├─ buildStageDetails     → pairs stage names with timings + notes
       │    └─ returns typed artifact object
       ├─ renderArtifact(artifact)
       │    ├─ compareState.artifact = artifact
       │    ├─ compareState.artifactToken = '<path> :: <timestamp>'
       │    ├─ setText / setStateValue on all <dd> elements
       │    ├─ renderStages(stages, stageTimings)
       │    ├─ renderCompareCanvas(artifact)
       │    └─ syncModeButtons()
       └─ setLoading(false)          → re-enables button

  [On any error]
       ├─ if no prior artifact: compareState.artifactToken = '—', setEmptyState()
       └─ setBanner('Failed to parse or validate JSON artifact: <message>', {type: 'error'})
```

### 3.4 Compare mode toggle

```
User clicks a mode button (Side-by-side / Overlay / Timeline)
  └─ 'click' event → setCompareMode(button.dataset.mode)
       ├─ normalizes unknown mode → 'side-by-side' + error banner
       ├─ compareState.activeMode = normalizedMode
       ├─ setText on #compare-mode, #compare-mode-title, #compare-mode-description
       ├─ renderCompareCanvas(compareState.artifact)
       │    └─ rebuilds #stage-board with new layout (grid / stack / timeline)
       ├─ syncModeButtons()         → updates .is-active and aria-pressed
       └─ setBanner(status message)
```

---

## 4. Artifact Data Source (`artifacts/`)

Artifacts are **`live_runtime_result.json`** documents validated by **`normalizeArtifact()`** (matching the **`live_runtime_result.schema.json`** assumptions).

Artifacts reach the shell through **any combination** of:

1. **`?artifact=`** ([, **`artifact2=`**][, **`benchmark=`]]) — `fetch` on the local demo origin.
2. **Upload separation** workflow (`POST /api/separate`).
3. **Manual loaders → Artifact file** (`<input type="file">` JSON read).

Serving `artifacts/` beside `ui/` is required for **`fetch`** auto-loading (launcher default path).

### 4.1 Expected locations and WAV companions

Runs typically emit:

```
artifacts/live/<run-id>/live_runtime_result.json
artifacts/live/<run-id>/mix.wav          # succeeds only when CLI returns exit code 0
artifacts/live/<run-id>/vocals.wav
artifacts/live/<run-id>/drums.wav
artifacts/live/<run-id>/bass.wav
artifacts/live/<run-id>/other.wav
```

**`mix.wav`:** mono 16‑bit PCM rendition of decoded input—used for the Input waveform/spectrogram and Play when JSON `input` points at `.mp4` / `.mp3` rather than PCM `.wav`.

Older smoke outputs without **`mix.wav`** still render stem canvases whenever the WAVs exist under `artifacts/`; regenerate or use Manual loaders for Input / playback parity.

### 4.2 Required JSON schema

`normalizeArtifact()` validates every field. All fields are required unless noted.

```json
{
  "input": "string — original input path",
  "status": "ok | error",
  "timestamp": "string — ISO 8601",
  "health_state": "healthy | degraded | fallback",
  "health_reason": "string",
  "requested_model_path": "string",
  "model_path": "string",
  "fallback_applied": "boolean",
  "stft_ms": "number (finite)",
  "infer_ms": "number (finite)",
  "istft_ms": "number (finite)",
  "total_ms": "number (finite)",
  "chunk_duration_s": "number (finite)",
  "sample_rate_hz": "integer ≥ 8000",
  "chunk_index": "integer ≥ 0",
  "queue_depth": "integer ≥ 0",
  "drop_count": "integer ≥ 0",
  "error_stage": "string | null",
  "error_message": "string | null",
  "stem_paths": {
    "vocals": "string",
    "drums": "string",
    "bass": "string",
    "other": "string"
  },
  "source": {
    "kind": "string",
    "reference": "string",
    "metadata": {
      "source_label": "string (optional)",
      "...": "any additional fields preserved as-is"
    }
  },
  "metadata": {
    "device_requested": "string",
    "device_used": "string",
    "mode": "string",
    "clock_source": "string",
    "clock_fallback": "boolean",
    "samples_processed": "integer ≥ 0",
    "channels": "integer ≥ 0",
    "sample_width_bytes": "integer ≥ 0",
    "stages": ["string", "…"],
    "stage_timings": "array | object | null"
  }
}
```

`stage_timings` is flexible: an array is interpreted as index-aligned with `stages`; an object is keyed by stage name.

### 4.3 Stem paths versus canvas rendering

Stem path strings populate the **Stem** panel verbatim while **Canvas lanes** concurrently try to **`fetch`** the corresponding WAV URLs (artifact JSON load path or manual WAV selection). Playback uses **only** the Input/`mix.wav` binding described in §2.2—not the stem blobs.

---

## 5. Compare Modes

When **`artifact2` is absent**, modes affect only the **`#stage-board`** flow. **`artifact2` present**: the dual timing board swaps in (`#compare-dual-board`) while waveform lanes obey §2.2 (primary vs secondary stem fetch).

| Mode key | Layout class | Description |
|---|---|---|
| `side-by-side` | `compare-stage-grid` | Three-column CSS grid; each stage card gets equal weight. |
| `overlay` | `compare-stage-stack` | Cards stacked with `--overlay-offset` and `--overlay-scale` CSS custom properties creating a depth effect. Each successive card is offset 18 px and scaled down by 4.5%. |
| `timeline` | `compare-stage-timeline` | Ordered list with a `--timeline-rail` vertical connector line and a circular bullet before each item. Cards rendered in compact mode. |

All three modes share the same `buildStageCard()` factory. Mode-specific builders (`buildStageGrid`, `buildOverlayStageStack`, `buildTimelineStageList`) simply wrap cards in the appropriate container element.

---

## 6. CSS Design System

`styles.css` uses CSS custom properties on `:root` (dark color scheme). Key tokens:

| Token | Value | Usage |
|---|---|---|
| `--bg` | `#07111c` | Page background base |
| `--surface` | `rgba(13,23,41,0.8)` | Card surfaces |
| `--accent` | `#8ee3ff` | Eyebrow text, mode button active state, timeline bullets |
| `--accent-strong` | `#38bdf8` | Button gradients |
| `--danger` | `#fb7185` | Error text |
| `--danger-bg` | `rgba(127,29,29,0.56)` | Error banner background |
| `--muted` | `#9baac2` | Secondary text, dt labels |
| `--radius-xl` | `28px` | Card corners |

Health state color is set via CSS attribute selectors:

```css
#compare-health[data-state="healthy"] { color: #86efac; }
#compare-health[data-state="degraded"] { color: #fbbf24; }
#compare-health[data-state="fallback"] { color: #fdba74; }
```

Responsive breakpoints:

- **≤ 1120 px**: toolbar grid and stems card collapse to single column; stage grid drops to 2 columns.
- **≤ 900 px**: all multi-column grids collapse to single column; overlay stack disables offset transforms.

---

## 7. Launching Locally

### 7.1 Quick start

```bash
# From the repository root
python scripts/ui/serve_compare_demo.py
```

The server prints:

```
compare-demo: serving /path/to/repo at http://127.0.0.1:8000/ui/compare/
```

Open `http://127.0.0.1:8000/ui/compare/` in a browser.

### 7.2 CLI options

```
usage: serve_compare_demo.py [--bind BIND] [--port PORT] [--directory DIRECTORY]

Options:
  --bind BIND          Interface to bind to (default: 127.0.0.1)
  --port PORT          Port to listen on (default: 8000)
  --directory DIR      Directory to serve (default: repository root)
```

### 7.3 How the server works

`serve_compare_demo.py` uses Python's `http.server.SimpleHTTPRequestHandler` wrapped in a `ThreadingHTTPServer`. It serves the **repository root** so `ui/compare/`, **`artifacts/`**, **`fixtures/`**, and **`POST /api/separate`** all share one origin—a requirement for **`fetch`/`<audio>`** against `/artifacts/...` paths emitted by persisted JSON artifacts.

The server logs each request to stderr in the format:

```
compare-demo: 127.0.0.1 "GET /ui/compare/ HTTP/1.1" 200 -
```

Shut down with Ctrl+C; the server closes cleanly and prints `compare-demo: stopped`.

### 7.4 Loading an artifact (typical launcher flow)

1. Run `launch.py`, `scripts/live/run_live_separation.py`, or **Upload separation** so JSON + WAVs appear under **`artifacts/live/...`**.
2. Serve the demo: `python scripts/ui/serve_compare_demo.py`.
3. Open the launcher-printed **`/ui/compare/?artifact=/artifacts/live/…/live_runtime_result.json[+&benchmark=]`** URLs (or `/ui/demo/` legacy redirect targets).
4. The UI `fetch()`es artifacts + benchmark, auto-loads WAV canvases (`mix.wav`, stems); **Play/Pause** activates once Input binds (§2.2).
5. Optional: expand **Manual loaders** for bespoke JSON/evidence uploads or manual WAV troubleshooting.

Standalone **offline JSON-only** workflows still supported via **Manual loaders → Artifact loader** (`file:` origin means automatic WAV `fetch()` will fail—use **Waveform assets** loaders or open through the localhost server).

### 7.5 Manual loaders-only flow

1. Open `http://127.0.0.1:8000/ui/compare/` (or drag `ui/compare/index.html` for JSON-only previews).
2. Expand **Manual loaders**.
3. Select JSON → **Load artifact**.
4. (Optional) **Load WAVs** for Input/stems if auto-fetch fails.
5. Toggle compare modes identical to preload flow.

---

## 8. Test Coverage

The compare UI is exercised by Playwright tests in `tests/ui/`. The tests interact with the UI via `data-testid` attributes that mirror the element `id`s. Key test IDs:

| `data-testid` | Element purpose |
|---|---|
| `selected-file` | File selection feedback paragraph |
| `error-banner` | Error feedback banner |
| `status-banner` | Status feedback banner |
| `mode-button-side-by-side` | Side-by-side mode toggle |
| `mode-button-overlay` | Overlay mode toggle |
| `mode-button-timeline` | Timeline mode toggle |
| `compare-mode` | Active mode key display |
| `compare-mode-title` | Active mode human label |
| `compare-canvas` | Stage showcase container |
| `stage-board` | Rebuilt per-render stage area |
| `compare-empty-state` | Empty placeholder before load |
| `compare-stems-list` | Stems DL inside the canvas |
| `source-panel` | Source info card |
| `health-panel` | Health info card |
| `timing-panel` | Timing info card |
| `stem-panel` | Stem paths card |
| `provenance-panel` | Full provenance card |
| `stages-list` | Stage list in provenance panel |

`window.__compareState`, `window.__setCompareMode`, and `window.__loadCompareArtifact` are exposed for direct Playwright page evaluation without needing to simulate full user gestures.
