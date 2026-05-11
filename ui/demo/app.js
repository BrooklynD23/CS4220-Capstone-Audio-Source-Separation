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

    el.statusLine.textContent = `Done in ${((Date.now() - startMs) / 1000).toFixed(1)}s`;

    await renderStems(result.stem_urls);
    renderPerf(result.timings, result.device_used);
    await loadBenchmarkTable();

    el.waveformSection.hidden = false;
    el.perfSection.hidden = false;
    el.benchmarkSection.hidden = false;
  } catch (err) {
    showError(`Request failed: ${err.message}`);
  } finally {
    clearInterval(timer);
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
    const tdKind = document.createElement('td');
    tdKind.textContent = row.kind;
    const tdMs = document.createElement('td');
    tdMs.textContent = row.ms.toFixed(2);
    const tdSpeedup = document.createElement('td');
    tdSpeedup.textContent = speedup;
    const tdSdr = document.createElement('td');
    tdSdr.textContent = row.sdr;
    tr.append(tdKind, tdMs, tdSpeedup, tdSdr);
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
