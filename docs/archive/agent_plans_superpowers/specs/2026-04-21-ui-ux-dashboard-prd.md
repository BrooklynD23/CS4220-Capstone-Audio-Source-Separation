# UI/UX PRD — Audio Source Separation Dashboard (Rebuild)

**Project:** CS4220 Capstone — Audio Source Separation (GPU-accelerated, real-time-ish pipeline)

**Audience:** Design + implementation agents (e.g., *Google Stitch*) rebuilding the UI from scratch.

**Default theme:** Dark-first, NVIDIA-inspired black/green (eye-friendly). Optional light theme.

**Primary mode:** **Run + Inspect** (create a separation run, then inspect artifacts, stems, graphs, and telemetry).

---

## 1) Context: what exists today

### Current UI surface (baseline)
- A static “compare shell” under `ui/compare/` that:
  - Loads one `live_runtime_result.json` file from disk.
  - Shows:
    - source identity (`source.kind`, `source.reference`)
    - health (`health_state`, `health_reason`, model fallback)
    - timing (stft/infer/istft/total)
    - stem file paths (vocals/drums/bass/other)
    - provenance (`device_requested`, `device_used`, etc.)
  - Provides three layout modes (side-by-side / overlay / timeline).
- **Gap:** There is no first-class “dashboard”.
- **Gap:** No audio signal graphs (waveform/spectrogram).
- **Gap:** Limited visibility into performance/acceleration beyond a few timing numbers.

### Key data artifacts available today
These JSON schemas exist and should be treated as first-class UI inputs:
- `artifacts/schema/live_runtime_result.schema.json`
- `artifacts/schema/timing_result.schema.json`
- `artifacts/schema/live_throughput_result.schema.json`
- `artifacts/schema/mic_latency_result.schema.json`

**Important:** The UI should be artifact-driven: the authoritative record of a run is the artifact JSON + stem WAV outputs.

---

## 2) Goals / non-goals

### Goals
1. Provide a **smooth dashboard UX** that works for:
   - capstone demo storytelling
   - debugging and performance inspection
   - comparing CPU vs GPU behavior
2. Make the UI a **single pane of glass** for:
   - input/source identity
   - model + device provenance (requested vs effective)
   - separation outputs (stems) with audio playback
   - **audio signal graphs** (waveforms + spectrograms)
   - **runtime telemetry** to measure accelerated computing (GPU) impact
3. Be **progressive**:
   - runs locally (localhost) with local file paths and local execution
   - can later run hosted (uploads + server-managed artifact store)

### Non-goals (v1)
- Real-time streaming visualizations synchronized to a live GPU pipeline (future).
- Collaborative multi-user features (future).
- Full training/evaluation management UI (future).

---

## 3) Personas & key use cases

### Personas
- **Student/Presenter:** wants a clean story: upload → run → show stems + speed/telemetry.
- **Engineer/Debugger:** wants deep artifact inspection, errors, timings, and comparisons.
- **Instructor/Reviewer:** wants credibility: evidence of GPU acceleration, clear provenance, reproducible artifacts.

### Top use cases
1. Run separation on an MP3 and inspect stems with waveforms/spectrograms.
2. Run CPU vs GPU with same settings; compare speedup and stage timing.
3. Run UMX vs Demucs request path; confirm model resolution + fallback telemetry.
4. Inspect a previously generated artifact JSON (no rerun).
5. View benchmark results (throughput / mic latency) and interpret “is this real-time capable?”.

---

## 4) Information architecture (Approach B — recommended)

**App layout:** left navigation + top bar.

### Left navigation (core)
- **Home**
- **New Run**
- **Runs** (history)
- **Inspect Artifact**
- **Compare Runs**
- **Benchmarks**
- **System / Device**
- **Settings** (theme, units)

### Top bar
- Project title + environment badge (Local / Hosted)
- Primary CTA (contextual): “New Run”
- Quick status: device used (CPU/GPU), last run status, last error indicator

---

## 5) Visual design system (NVIDIA-inspired, eye-friendly)

### Brand direction
- **Dark default**: near-black backgrounds, subtle elevation, low-contrast borders.
- **Accent**: NVIDIA green for primary actions + success states.
- **Secondary accents**: cyan/teal for charts; amber for warnings; red for failures.

### Suggested token palette (dark)
(Provide these as CSS variables/tokens in the design system)
- `--bg-0`: #0B0F0C (near-black with green-neutral)
- `--bg-1`: #0F1511
- `--surface-0`: rgba(20, 28, 22, 0.72)
- `--surface-1`: rgba(28, 38, 30, 0.82)
- `--border-0`: rgba(198, 255, 214, 0.12)
- `--text-0`: #EAF2EC
- `--text-1`: rgba(234, 242, 236, 0.72)
- `--accent-green`: #76B900 (NVIDIA green)
- `--accent-green-strong`: #9DFF00
- `--accent-cyan`: #40C9FF
- `--warn`: #F4B740
- `--danger`: #FF4D6D

### Light theme (optional)
- Keep NVIDIA green as accent; shift surfaces to soft off-white.
- Must preserve chart legibility and contrast ratios.

### Typography
- UI: **Inter** (or system UI) for readability.
- Mono: **JetBrains Mono** for paths, telemetry keys, CLI commands.

### Layout + density
- Prefer “comfortable” spacing; allow a compact mode toggle for engineering users.
- Use cards + grouped sections with sticky section headers on long pages.

### Motion
- Subtle, 150–250ms transitions.
- Skeleton loading for long-running runs.
- Avoid heavy animations during audio playback.

---

## 6) Data model (UI-level)

### Run record (conceptual)
A “Run” is the thing shown in **Run Detail**.

**Minimum fields** (mapped from artifacts):
- `id` (UUID or deterministic hash)
- `created_at`
- `source`: kind/reference/metadata
- `settings`: model_path requested, chunk_duration_s, sample_rate_hz, device_requested
- `result`: status, error_stage, error_message
- `health`: health_state, health_reason, fallback_applied, requested_model_path, model_path
- `telemetry`: stage timings, queue depth, drop count, samples_processed, channels
- `outputs`: stem_paths (vocals/drums/bass/other)
- `benchmarks?`: throughput result, mic latency result (if run in those modes)

### Mapping to current artifact schemas
- **Live runtime:** `live_runtime_result.json`
  - Stage timings: `stft_ms`, `infer_ms`, `istft_ms`, `total_ms`
  - Device: `metadata.device_requested`, `metadata.device_used`
  - Health: `health_state`, `health_reason`, fallback + model paths
  - Queue/drop: `queue_depth`, `drop_count`
  - Outputs: `stem_paths.*`
- **Timing result:** `timing_result.json` (same timing shape, used for dedicated timing runs)
- **Throughput:** `live_throughput_result.json`
- **Mic latency:** `mic_latency_result.json`

---

## 7) Telemetry & acceleration metrics (what the UI must compute/display)

### Stage timing visualization
- A stacked bar (“waterfall”) for `stft_ms`, `infer_ms`, `istft_ms`, `total_ms`.
- A table with exact numeric values + units.

### Real-time capability indicators
UI should compute:
- **Chunk budget (ms)** = `chunk_duration_s * 1000`
- **Real-time factor (RTF)** = `total_ms / chunk_budget_ms`
  - `RTF <= 1.0` → *real-time capable for this chunk size*
- **Inference share** = `infer_ms / total_ms`

### GPU acceleration proof (comparative)
On **Compare Runs**, compute:
- Speedup:
  - `speedup_total = cpu.total_ms / gpu.total_ms`
  - `speedup_infer = cpu.infer_ms / gpu.infer_ms`
- Highlight if:
  - GPU is faster but STFT/ISTFT dominates (actionable insight)

### Health + fallback
- Health states: `healthy`, `degraded`, `fallback`.
- Always show:
  - requested model path vs effective model path
  - fallback applied boolean
  - health reason message (human-readable)

### Queue/drop
- Display `queue_depth`, `drop_count`.
- If `drop_count > 0`, show degraded badge and explain impact.

### (Recommended future) System snapshot
If available later, add a “System” section:
- GPU name, driver, CUDA version, VRAM, compute capability.
- This may require a new artifact schema. UI should be designed to accept it.

---

## 8) Audio visualization requirements (requested)

### 8.1 Waveform graph
**Must have:**
- Input waveform.
- Waveforms for each stem (vocals/drums/bass/other).
- Zoom + pan + selection range.
- Cursor scrub + timestamp readout.
- Optional RMS/peak overlays.

**UX notes:**
- Provide a “stem mixer” panel: solo/mute stems.
- Provide “A/B” toggles: input vs vocals, etc.

### 8.2 Spectrogram graph
**Must have:**
- Spectrogram for input.
- Spectrogram for selected stem.
- Frequency scale controls (linear/log).
- Colormap designed for dark theme (avoid neon glare).

### 8.3 Playback
**Must have:**
- Player for input and each stem.
- Synchronized playback toggle (play all at once) if feasible.
- Download buttons per stem.

### 8.4 Signal summary metrics
For the selected track (input or stem), show:
- duration
- sample rate
- channels
- peak amplitude / RMS (computed client-side from WAV if local)

---

## 9) Screen-by-screen requirements

### 9.1 Home
- Cards:
  - “Last run” status + timestamp
  - Device (requested/used)
  - Last total_ms + RTF
  - Last throughput (if available)
  - Last mic latency (if available)
- Recent runs list (5–10).

### 9.2 New Run (wizard)
**Step 1 — Source**
- Source mode: mp3 / video-audio / mic
- Input selection:
  - Local: file picker + drag/drop
  - Hosted: upload

**Step 2 — Settings**
- Model: UMX / Demucs request
- Device requested: CPU / GPU
- Chunk duration
- Sample rate

**Step 3 — Output**
- Local: output directory + artifact path (advanced)
- Hosted: destination project/run name

**Step 4 — Run**
- Start run
- Live log output (sanitized)
- Status steps: decode → stft → infer → istft → write stems → publish artifact

### 9.3 Runs (history)
- Table: run id, timestamp, source, model, device, status, total_ms, RTF.
- Filters: status, device_used, model_path, source.kind.

### 9.4 Run Detail (primary dashboard)
**Layout (recommended)**
- Header: Run title + status badge + quick actions (download, copy summary)
- Row 1: Source card + Health card + Performance summary card
- Row 2: Stage timings chart (waterfall) + queue/drop + provenance
- Row 3: Audio visualization (waveform + spectrogram tabs)
- Row 4: Stem mixer + stem file list + players

**Required sections**
- Source (kind/reference/metadata)
- Model provenance (requested vs effective)
- Device requested vs used
- Health + reason
- Stage timings + RTF
- Queue/drop
- Stems (paths + download + playback)
- Graphs: waveform + spectrogram

### 9.5 Inspect Artifact
- Load artifact JSON (local pick / upload).
- Render the exact same Run Detail components.
- If stems are missing/unresolvable:
  - show missing state per stem
  - keep artifact visible (do not blank the page)

### 9.6 Compare Runs
- Pick two runs.
- Side-by-side cards:
  - timings + RTF
  - speedups
  - model/device provenance
  - health comparison
- Optional: overlay waveforms for the same stem.

### 9.7 Benchmarks
- Throughput page:
  - chart: throughput_chunks_per_second
  - wall_clock_ms per chunk
  - show device_requested/used, source_mode
- Mic latency page:
  - end_to_end_latency_ms
  - capture_latency_ms
  - capture backend

### 9.8 System / Device
- Local:
  - environment notes, browser support
  - optionally show detected GPU/CPU info if available
- Hosted:
  - account/project settings (future)

---

## 10) Error/empty states (must be explicit)

Principle: **fail loudly, preserve last-known-good view**.

- No file selected → clear prompt.
- Artifact schema mismatch → show validation error banner + keep any prior artifact loaded.
- Stem path missing → show per-stem missing UI, not a global failure.
- Run failed → show `error_stage` and `error_message` prominently, plus any partial telemetry.
- Fallback applied → show “Fallback” badge (not an error), with explanation.

---

## 11) Accessibility (WCAG-minded)

- Keyboard navigation for all controls.
- Visible focus states.
- ARIA labels for charts (summaries + data tables as accessible fallback).
- Color contrast: ensure green accents do not reduce readability.
- Avoid encoding status solely by color (icons + labels).

---

## 12) Performance requirements (UI)

- Large WAV/spectrogram rendering must remain responsive.
- Prefer:
  - canvas/WebGL for graphs
  - web workers for heavy transforms (future)
- Lazy-load heavy panels (spectrogram) when tab opens.

---

## 13) Progressive Local vs Hosted requirements

### Local mode (v1 target)
- Run orchestration can be:
  - a local CLI wrapper, or
  - a local server that starts jobs
- Inputs and outputs are local paths.

### Hosted mode (design-ready)
- Same UI flows, but:
  - input is uploaded
  - runs are jobs with status polling
  - artifacts/stems stored server-side

**Design requirement:** avoid hard-coding “local file path” assumptions into layout; model “input reference” generically.

---

## 14) Acceptance criteria (v1)

1. User can create a new run (local) and lands on Run Detail.
2. Run Detail displays:
   - source + health + timings + stems
   - device requested vs used
   - RTF and stage waterfall
3. Waveform graphs exist for input + all stems.
4. Spectrogram exists for input + selected stem.
5. Compare Runs shows CPU vs GPU speedup and timing breakdown.
6. Benchmarks pages load and present throughput and mic latency results.
7. Theme: dark default NVIDIA-inspired, optional light mode.

---

## 15) Design handoff notes for Google Stitch

### Deliverables expected
- Component library + tokens (dark + light)
- Full page designs for each core screen
- Run Detail (primary) in both “no artifact yet” and “loaded artifact ok” states
- Error states: schema mismatch, missing stem file, runtime error
- Charts: waveform + spectrogram mocks with realistic density

### Visual tone
- Technical, modern, high trust.
- “Lab instrument panel” feel, but not cluttered.
- Green accents used sparingly (CTAs, health badges, key highlights).

---

## Appendix A — Key fields to surface (live runtime)

From `live_runtime_result.json`:
- `source.kind`, `source.reference`, `source.metadata`
- `input`, `sample_rate_hz`, `chunk_duration_s`, `chunk_index`
- `stft_ms`, `infer_ms`, `istft_ms`, `total_ms`
- `status`, `error_stage`, `error_message`, `timestamp`
- `health_state`, `health_reason`
- `requested_model_path`, `model_path`, `fallback_applied`
- `queue_depth`, `drop_count`
- `stem_paths.vocals|drums|bass|other`
- `metadata.device_requested`, `metadata.device_used`, `metadata.mode`, `metadata.samples_processed`, `metadata.channels`, `metadata.sample_width_bytes`, `metadata.stages`
