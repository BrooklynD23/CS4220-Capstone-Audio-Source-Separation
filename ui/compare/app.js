import { decodePcmWav, drawWaveform, drawSpectrogram } from '../shared/audio-render.js';
import {
  clearPersistedArtifactsRoot,
  isArtifactsScopePickerSupported,
  loadPersistedArtifactsRoot,
  persistArtifactsFolderFromUser,
  requestDirectoryReadAccess,
  runScopedKindPicker,
} from './fs-artifacts-scope.js';

const LANE_PLAY_KEYS = ['input', 'vocals', 'drums', 'bass', 'other'];

function lanePlayButton(lane) {
  return document.querySelector(`[data-testid="lane-play-${lane}"]`);
}

const MODE_CONFIG = {
  'side-by-side': {
    title: 'Side-by-side',
    description: 'Each showcase stage gets the same visual weight so source, timing, and stems stay easy to compare.'
  },
  overlay: {
    title: 'Overlay',
    description: 'Stages stack into a layered composition to emphasize how the same artifact is being re-expressed.'
  },
  timeline: {
    title: 'Timeline / sequence',
    description: 'Stages fall into a vertical sequence with connective rails for quick runtime reading.'
  },
};

const STAGE_NOTES = {
  stft: 'Spectral framing and chunk alignment',
  infer: 'Model inference over the shared latent',
  istft: 'Waveform reconstruction and stem writeout',
  demux: 'Audio-first extraction from the video container',
  decode: 'Decode and normalize the incoming source',
  mixdown: 'Final stem mixdown and packaging',
};

const elements = {
  uploadFile: document.getElementById('upload-file'),
  uploadDevice: document.getElementById('upload-device'),
  uploadSeparateBtn: document.getElementById('upload-separate-btn'),
  uploadStatusLine: document.getElementById('upload-status-line'),
  fileInput: document.getElementById('artifact-file'),
  loadButton: document.getElementById('load-button'),
  benchmarkFileInput: document.getElementById('benchmark-file'),
  benchmarkSelectedLine: document.getElementById('benchmark-selected-line'),
  loadBenchmarkButton: document.getElementById('load-benchmark-button'),
  benchmarkKindCpu: document.getElementById('benchmark-kind-cpu'),
  benchmarkKindGpu: document.getElementById('benchmark-kind-gpu'),
  benchmarkCpuMs: document.getElementById('benchmark-cpu-ms'),
  benchmarkGpuMs: document.getElementById('benchmark-gpu-ms'),
  benchmarkDelta: document.getElementById('benchmark-delta'),
  inputAudioFile: document.getElementById('input-audio-file'),
  stemAudioFiles: document.getElementById('stem-audio-files'),
  loadAudioButton: document.getElementById('load-audio-button'),
  audioFileCount: document.getElementById('audio-file-count'),
  waveformCanvases: {
    input: document.getElementById('waveform-input'),
    vocals: document.getElementById('waveform-vocals'),
    drums: document.getElementById('waveform-drums'),
    bass: document.getElementById('waveform-bass'),
    other: document.getElementById('waveform-other'),
  },
  spectrogramCanvases: {
    input: document.getElementById('spectrogram-input'),
    vocals: document.getElementById('spectrogram-vocals'),
    drums: document.getElementById('spectrogram-drums'),
    bass: document.getElementById('spectrogram-bass'),
    other: document.getElementById('spectrogram-other'),
  },
  playbackToggle: document.getElementById('playback-toggle'),
  playbackState: document.getElementById('playback-state'),
  selectedFile: document.getElementById('selected-file'),
  errorBanner: document.getElementById('error-banner'),
  statusBanner: document.getElementById('status-banner'),
  sourceKind: document.getElementById('source-kind'),
  sourceLabel: document.getElementById('source-label'),
  sourceReference: document.getElementById('source-reference'),
  sourceMetadata: document.getElementById('source-metadata'),
  artifactPath: document.getElementById('artifact-path'),
  compareMode: document.getElementById('compare-mode'),
  compareModeTitle: document.getElementById('compare-mode-title'),
  compareModeDescription: document.getElementById('compare-mode-description'),
  compareToken: document.getElementById('compare-token'),
  compareHealth: document.getElementById('compare-health'),
  compareModeButtons: Array.from(document.querySelectorAll('.mode-button[data-mode]')),
  healthState: document.getElementById('health-state'),
  healthReason: document.getElementById('health-reason'),
  requestedModelPath: document.getElementById('requested-model-path'),
  modelPath: document.getElementById('model-path'),
  fallbackApplied: document.getElementById('fallback-applied'),
  timingStft: document.getElementById('timing-stft'),
  timingInfer: document.getElementById('timing-infer'),
  timingIstft: document.getElementById('timing-istft'),
  timingTotal: document.getElementById('timing-total'),
  timingChunk: document.getElementById('timing-chunk'),
  sampleRate: document.getElementById('sample-rate'),
  stemVocals: document.getElementById('stem-vocals'),
  stemDrums: document.getElementById('stem-drums'),
  stemBass: document.getElementById('stem-bass'),
  stemOther: document.getElementById('stem-other'),
  queueDepth: document.getElementById('queue-depth'),
  dropCount: document.getElementById('drop-count'),
  inputPath: document.getElementById('input-path'),
  status: document.getElementById('status'),
  timestamp: document.getElementById('timestamp'),
  chunkIndex: document.getElementById('chunk-index'),
  deviceRequested: document.getElementById('device-requested'),
  deviceUsed: document.getElementById('device-used'),
  mode: document.getElementById('mode'),
  clockSource: document.getElementById('clock-source'),
  clockFallback: document.getElementById('clock-fallback'),
  samplesProcessed: document.getElementById('samples-processed'),
  channels: document.getElementById('channels'),
  sampleWidth: document.getElementById('sample-width'),
  stagesList: document.getElementById('stages-list'),
  compareCanvas: document.getElementById('compare-canvas'),
  compareDualBoard: document.getElementById('compare-dual-board'),
  compareDualColumns: document.getElementById('compare-dual-columns'),
  compareDualLeftRole: document.getElementById('compare-dual-left-role'),
  compareDualLeftTotal: document.getElementById('compare-dual-left-total'),
  compareDualRightRole: document.getElementById('compare-dual-right-role'),
  compareDualRightTotal: document.getElementById('compare-dual-right-total'),
  compareDualSpeedup: document.getElementById('compare-dual-speedup'),
  stageBoard: document.getElementById('stage-board'),
  stageBoardCaption: document.getElementById('stage-board-caption'),
  finalStemsLabel: document.getElementById('final-stems-label'),
  finalStemsDetails: document.getElementById('final-stems-details'),
  finalStemsStrip: document.querySelector('.final-stems-strip'),
  runtimeHealthText: document.getElementById('runtime-health-text'),
  runtimeSourceText: document.getElementById('runtime-source-text'),
};

const compareState = {
  artifact: null,
  artifact2: null,
  artifactToken: '—',
  artifactToken2: '—',
  activeMode: 'side-by-side',
  lastModeMessage: 'Awaiting a loaded artifact.',
  audioElement: null,
  laneUrls: {
    input: null,
    vocals: null,
    drums: null,
    bass: null,
    other: null,
  },
  blobUrlsToRevoke: [],
  activeLaneKey: null,
  benchmarkLoaded: false,
};

window.__compareState = compareState;
window.__setCompareMode = setCompareMode;
window.__loadCompareArtifact = loadArtifactFromFile;
window.__loadCompareArtifactFromUrl = loadArtifactFromUrl;

const emptyState = {
  source: { kind: '—', label: '—', reference: '—', metadata: '—' },
  health: {
    state: '—',
    reason: '—',
    requestedModelPath: '—',
    modelPath: '—',
    fallbackApplied: '—',
  },
  timing: {
    stft: '—',
    infer: '—',
    istft: '—',
    total: '—',
    chunk: '—',
    sampleRate: '—',
  },
  stems: { vocals: '—', drums: '—', bass: '—', other: '—', queueDepth: '—', dropCount: '—' },
  provenance: {
    input: '—',
    status: '—',
    timestamp: '—',
    chunkIndex: '—',
    deviceRequested: '—',
    deviceUsed: '—',
    mode: '—',
    clockSource: '—',
    clockFallback: '—',
    samplesProcessed: '—',
    channels: '—',
    sampleWidth: '—',
    stages: ['—'],
  },
};

function setBanner(message, { type = 'status' } = {}) {
  if (type === 'error') {
    elements.errorBanner.textContent = message;
    elements.errorBanner.classList.remove('is-hidden');
    elements.statusBanner.textContent = compareState.artifact
      ? `Loaded artifact hidden while the error is shown.`
      : 'Artifact load failed. Review the error banner and retry.';
    compareState.lastModeMessage = message;
    return;
  }

  elements.errorBanner.textContent = '';
  elements.errorBanner.classList.add('is-hidden');
  elements.statusBanner.textContent = message;
  compareState.lastModeMessage = message;
}

function setLoading(isLoading) {
  elements.loadButton.disabled = isLoading;
  elements.loadButton.textContent = isLoading ? 'Loading…' : 'Load artifact';
  if (isLoading) {
    elements.statusBanner.textContent = 'Loading artifact…';
  }
}

function setText(node, value) {
  node.textContent = value;
}

function setStateValue(node, value) {
  setText(node, value);
  if (value === 'healthy' || value === 'degraded' || value === 'fallback') {
    node.dataset.state = value;
  } else {
    delete node.dataset.state;
  }
}

function setEmptyState() {
  compareState.artifact = null;
  compareState.artifact2 = null;
  compareState.artifactToken = '—';
  compareState.artifactToken2 = '—';
  setDualCompareVisibility(false);
  setText(elements.sourceKind, emptyState.source.kind);
  setText(elements.sourceLabel, emptyState.source.label);
  setText(elements.sourceReference, emptyState.source.reference);
  setText(elements.sourceMetadata, emptyState.source.metadata);
  setText(elements.artifactPath, '—');

  setText(elements.compareMode, compareState.activeMode);
  setText(elements.compareModeTitle, MODE_CONFIG[compareState.activeMode].title);
  setText(elements.compareModeDescription, MODE_CONFIG[compareState.activeMode].description);
  setText(elements.compareToken, compareState.artifactToken);
  setStateValue(elements.compareHealth, '—');
  setText(elements.runtimeHealthText, 'No artifact loaded');
  setText(elements.runtimeSourceText, 'Source kind unavailable');

  setStateValue(elements.healthState, emptyState.health.state);
  setText(elements.healthReason, emptyState.health.reason);
  setText(elements.requestedModelPath, emptyState.health.requestedModelPath);
  setText(elements.modelPath, emptyState.health.modelPath);
  setText(elements.fallbackApplied, emptyState.health.fallbackApplied);

  setText(elements.timingStft, emptyState.timing.stft);
  setText(elements.timingInfer, emptyState.timing.infer);
  setText(elements.timingIstft, emptyState.timing.istft);
  setText(elements.timingTotal, emptyState.timing.total);
  setText(elements.timingChunk, emptyState.timing.chunk);
  setText(elements.sampleRate, emptyState.timing.sampleRate);

  setText(elements.stemVocals, emptyState.stems.vocals);
  setText(elements.stemDrums, emptyState.stems.drums);
  setText(elements.stemBass, emptyState.stems.bass);
  setText(elements.stemOther, emptyState.stems.other);
  setText(elements.queueDepth, emptyState.stems.queueDepth);
  setText(elements.dropCount, emptyState.stems.dropCount);

  setText(elements.inputPath, emptyState.provenance.input);
  setText(elements.status, emptyState.provenance.status);
  setText(elements.timestamp, emptyState.provenance.timestamp);
  setText(elements.chunkIndex, emptyState.provenance.chunkIndex);
  setText(elements.deviceRequested, emptyState.provenance.deviceRequested);
  setText(elements.deviceUsed, emptyState.provenance.deviceUsed);
  setText(elements.mode, emptyState.provenance.mode);
  setText(elements.clockSource, emptyState.provenance.clockSource);
  setText(elements.clockFallback, emptyState.provenance.clockFallback);
  setText(elements.samplesProcessed, emptyState.provenance.samplesProcessed);
  setText(elements.channels, emptyState.provenance.channels);
  setText(elements.sampleWidth, emptyState.provenance.sampleWidth);

  renderStages(['—']);
  renderCompareCanvas(null);
  syncModeButtons();
  detachCompareAudioPlayback();
}

function setEmptyBenchmarkState() {
  setText(elements.benchmarkKindCpu, '—');
  setText(elements.benchmarkKindGpu, '—');
  setText(elements.benchmarkCpuMs, '—');
  setText(elements.benchmarkGpuMs, '—');
  setText(elements.benchmarkDelta, '—');
  setText(elements.benchmarkSelectedLine, 'No benchmark JSON selected');
}

function renderStages(stages, stageTimings = {}) {
  elements.stagesList.innerHTML = '';
  const normalizedStages = stages.length > 0 ? stages : ['—'];

  normalizedStages.forEach((stage, index) => {
    const li = document.createElement('li');
    li.dataset.state = stage === '—' ? 'empty' : 'loaded';
    li.dataset.stage = stage;
    const label = document.createElement('span');
    label.className = 'stage-pill';
    label.textContent = `Stage ${String(index + 1).padStart(2, '0')}`;
    const title = document.createElement('strong');
    title.textContent = stage;
    const timing = document.createElement('span');
    timing.className = 'stage-timing';
    const stageTiming = typeof stageTimings?.[stage] === 'number' ? `${stageTimings[stage].toFixed(2)} ms` : 'Timing unavailable';
    timing.textContent = stage === '—' ? 'No stage data loaded' : stageTiming;
    li.append(label, title, timing);
    elements.stagesList.appendChild(li);
  });
}

function toDisplayText(value, formatter = String) {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  return formatter(value);
}

function expectObject(value, path) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${path} must be an object`);
  }
  return value;
}

function expectString(value, path) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`${path} must be a non-empty string`);
  }
  return value.trim();
}

function expectNumber(value, path) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`${path} must be a finite number`);
  }
  return value;
}

function expectInteger(value, path, { min = Number.NEGATIVE_INFINITY } = {}) {
  if (!Number.isInteger(value)) {
    throw new Error(`${path} must be an integer`);
  }
  if (value < min) {
    throw new Error(`${path} must be greater than or equal to ${min}`);
  }
  return value;
}

function expectBoolean(value, path) {
  if (typeof value !== 'boolean') {
    throw new Error(`${path} must be a boolean`);
  }
  return value;
}

function maybeNumber(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function phaseSummary(phase) {
  if (!phase || typeof phase !== 'object') {
    return null;
  }
  const summary = phase.summary && typeof phase.summary === 'object' ? phase.summary : phase;
  const executionKind = summary.execution_kind || phase.execution_kind;
  const msPerChunk = maybeNumber(summary.wall_clock_ms_per_chunk);
  const throughput = maybeNumber(summary.throughput_chunks_per_second);
  if (typeof executionKind !== 'string' || msPerChunk === null) {
    return null;
  }
  return { executionKind, msPerChunk, throughput };
}

function normalizeBenchmarkPayload(payload) {
  const root = expectObject(payload, 'benchmark artifact');
  const candidates = [];

  if (Array.isArray(root.phases)) {
    root.phases.forEach((phase) => {
      const candidate = phaseSummary(phase);
      if (candidate) {
        candidates.push(candidate);
      }
    });
  } else {
    const candidate = phaseSummary(root);
    if (candidate) {
      candidates.push(candidate);
    }
  }

  if (candidates.length === 0) {
    throw new Error('benchmark artifact must contain throughput summaries with execution_kind and wall_clock_ms_per_chunk');
  }

  const cpu = candidates.find((candidate) => candidate.executionKind === 'cpu') || candidates[0];
  const accelerated = candidates.find((candidate) => candidate.executionKind !== 'cpu') || cpu;
  const delta = accelerated.msPerChunk > 0 ? cpu.msPerChunk / accelerated.msPerChunk : 0;
  return { cpu, accelerated, delta };
}

function renderBenchmarkComparison(comparison) {
  setText(elements.benchmarkKindCpu, comparison.cpu.executionKind);
  setText(elements.benchmarkKindGpu, comparison.accelerated.executionKind);
  setText(elements.benchmarkCpuMs, `${comparison.cpu.msPerChunk.toFixed(2)} ms`);
  setText(elements.benchmarkGpuMs, `${comparison.accelerated.msPerChunk.toFixed(2)} ms`);
  setText(elements.benchmarkDelta, `${comparison.delta.toFixed(2)}x`);
}

async function loadBenchmarkFromFile() {
  const file = elements.benchmarkFileInput.files?.[0];
  if (!file) {
    setEmptyBenchmarkState();
    setBanner('Select a benchmark JSON artifact before loading.', { type: 'error' });
    return;
  }

  try {
    const payload = JSON.parse(await file.text());
    const comparison = normalizeBenchmarkPayload(payload);
    renderBenchmarkComparison(comparison);
    compareState.benchmarkLoaded = true;
    setBanner(`Loaded benchmark evidence ${file.name}.`, { type: 'status' });
    syncBenchmarkChosenLabel();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setBanner(`Failed to parse or validate benchmark artifact: ${message}`, { type: 'error' });
  }
}

function setAudienceMode(isPreloaded) {
  document.body.dataset.mode = isPreloaded ? 'preloaded' : 'manual';
}

async function loadBenchmarkFromUrlSilent(resolvedUrlOrPath) {
  let resolvedUrl;
  try {
    resolvedUrl = resolveArtifactUrl(resolvedUrlOrPath);
  } catch {
    return false;
  }
  try {
    const response = await fetch(resolvedUrl.toString(), { cache: 'no-store' });
    if (!response.ok) {
      return false;
    }
    const payload = await response.json();
    const comparison = normalizeBenchmarkPayload(payload);
    renderBenchmarkComparison(comparison);
    compareState.benchmarkLoaded = true;
    return true;
  } catch {
    return false;
  }
}

function releaseInputLaneBlobOnly() {
  const prev = compareState.laneUrls.input;
  if (prev && typeof prev === 'string' && prev.startsWith('blob:')) {
    const idx = compareState.blobUrlsToRevoke.indexOf(prev);
    if (idx >= 0) {
      compareState.blobUrlsToRevoke.splice(idx, 1);
    }
    try {
      URL.revokeObjectURL(prev);
    } catch {
      /* ignore */
    }
  }
  compareState.laneUrls.input = null;
  if (compareState.activeLaneKey === 'input') {
    if (compareState.audioElement) {
      compareState.audioElement.pause();
      compareState.audioElement = null;
    }
    compareState.activeLaneKey = null;
    setPlaybackUiStopped();
  } else {
    refreshLanePlayButtons();
  }
}

function revokeLaneBlobUrls() {
  for (const u of compareState.blobUrlsToRevoke) {
    try {
      URL.revokeObjectURL(u);
    } catch {
      /* ignore */
    }
  }
  compareState.blobUrlsToRevoke = [];
}

function clearLaneUrlMap() {
  compareState.laneUrls = {
    input: null,
    vocals: null,
    drums: null,
    bass: null,
    other: null,
  };
}

function refreshLanePlayButtons() {
  for (const lane of LANE_PLAY_KEYS) {
    const btn = lanePlayButton(lane);
    if (!btn) {
      continue;
    }
    const hasUrl = Boolean(compareState.laneUrls[lane]);
    btn.disabled = !hasUrl;
    if (!hasUrl || compareState.activeLaneKey !== lane) {
      setText(btn, 'Play');
      btn.setAttribute('aria-pressed', 'false');
    }
  }
}

function playbackUrlFromRepoPath(stemPath) {
  const urlPath = stemPathToRepoUrlPath(stemPath);
  return new URL(urlPath, `${window.location.origin}/`).toString();
}

function registerBlobLaneUrl(lane, objUrl) {
  compareState.laneUrls[lane] = objUrl;
  compareState.blobUrlsToRevoke.push(objUrl);
  refreshLanePlayButtons();
}

function registerLaneUrl(lane, url) {
  compareState.laneUrls[lane] = url;
  refreshLanePlayButtons();
}

function setPlaybackUiStopped() {
  setText(elements.playbackState, 'stopped');
  setText(elements.playbackToggle, 'Play input');
  elements.playbackToggle.setAttribute('aria-pressed', 'false');
  for (const lane of LANE_PLAY_KEYS) {
    const btn = lanePlayButton(lane);
    if (!btn) {
      continue;
    }
    setText(btn, 'Play');
    btn.setAttribute('aria-pressed', 'false');
  }
  refreshLanePlayButtons();
}

function updatePlayingLaneUi(lane) {
  setText(elements.playbackState, 'playing');
  for (const k of LANE_PLAY_KEYS) {
    const btn = lanePlayButton(k);
    if (!btn) {
      continue;
    }
    if (k === lane) {
      setText(btn, 'Pause');
      btn.setAttribute('aria-pressed', 'true');
    } else {
      setText(btn, 'Play');
      btn.setAttribute('aria-pressed', 'false');
    }
  }
  if (lane === 'input') {
    setText(elements.playbackToggle, 'Pause input');
    elements.playbackToggle.setAttribute('aria-pressed', 'true');
  } else {
    setText(elements.playbackToggle, 'Play input');
    elements.playbackToggle.setAttribute('aria-pressed', 'false');
  }
}

function updatePausedLaneUi(lane) {
  setText(elements.playbackState, 'paused');
  const btn = lanePlayButton(lane);
  if (btn) {
    setText(btn, 'Play');
    btn.setAttribute('aria-pressed', 'false');
  }
  if (lane === 'input') {
    setText(elements.playbackToggle, 'Play input');
    elements.playbackToggle.setAttribute('aria-pressed', 'false');
  }
}

const MEDIA_PLAY_EXTENSIONS = /\.(?:mp3|m4a|aac|ogg|flac|wav|mp4|webm|mov)(?:\?|$)/i;

function clearInputWaveformVisualization() {
  const emptySamples = new Float32Array(0);
  drawWaveform(elements.waveformCanvases.input, emptySamples);
  drawSpectrogram(elements.spectrogramCanvases.input, emptySamples);
}

function detachCompareAudioPlayback() {
  if (compareState.audioElement) {
    compareState.audioElement.pause();
    compareState.audioElement = null;
  }
  compareState.activeLaneKey = null;
  revokeLaneBlobUrls();
  clearLaneUrlMap();
  setPlaybackUiStopped();
}

function attachPlaybackEndedHandler(audio) {
  audio.addEventListener('ended', () => {
    compareState.audioElement = null;
    compareState.activeLaneKey = null;
    setPlaybackUiStopped();
  });
}

/** When mix.wav/input.wav PCM fetch fails — bind `<audio>` to original media under artifacts/. */
function deriveBrowserMediaInputPath(artifact) {
  if (!artifact) {
    return null;
  }
  const input = String(artifact.provenance?.input || '').trim();
  if (!input || input.toLowerCase().endsWith('.wav')) {
    return null;
  }
  const lower = input.toLowerCase();
  if (!MEDIA_PLAY_EXTENSIONS.test(lower)) {
    return null;
  }
  return input;
}

function bindPlaybackFromSameOriginArtifactsPath(rawRepoPath) {
  let repoUrlPath;
  try {
    repoUrlPath = stemPathToRepoUrlPath(rawRepoPath);
  } catch {
    return false;
  }
  const resolvedUrl = new URL(repoUrlPath, `${window.location.origin}/`);
  if (resolvedUrl.origin !== window.location.origin) {
    return false;
  }
  releaseInputLaneBlobOnly();
  registerLaneUrl('input', resolvedUrl.toString());
  clearInputWaveformVisualization();
  return true;
}

function deriveInputWavePathForArtifact(artifact) {
  if (!artifact) {
    return null;
  }
  const input = String(artifact.provenance?.input || '').trim();
  if (input.toLowerCase().endsWith('.wav')) {
    return input;
  }
  const vocals = String(artifact.stems?.vocals || '').trim().replace(/\\/g, '/');
  const idx = vocals.lastIndexOf('/');
  if (idx < 0) {
    return null;
  }
  return `${vocals.slice(0, idx)}/mix.wav`;
}

async function autoLoadInputMixWaveform(artifact) {
  if (!artifact) {
    return;
  }
  const wavTry = deriveInputWavePathForArtifact(artifact);
  if (wavTry) {
    try {
      const urlPath = stemPathToRepoUrlPath(wavTry);
      const buf = await fetchWavArrayBuffer(urlPath);
      const samples = decodePcmWav(buf);
      drawWaveform(elements.waveformCanvases.input, samples);
      drawSpectrogram(elements.spectrogramCanvases.input, samples);
      releaseInputLaneBlobOnly();
      const blob = new Blob([buf], { type: 'audio/wav' });
      const objUrl = URL.createObjectURL(blob);
      registerBlobLaneUrl('input', objUrl);
      return;
    } catch {
      /* PCM path failed — browser media fallback below */
    }
  }

  const mediaPath = deriveBrowserMediaInputPath(artifact);
  if (mediaPath && bindPlaybackFromSameOriginArtifactsPath(mediaPath)) {
    return;
  }
}

async function finishPreloadExtras(benchmarkQuery) {
  const benchPath = benchmarkQuery && benchmarkQuery.trim()
    ? benchmarkQuery.trim()
    : '/artifacts/bench/capstone_evidence_manifest.json';
  await loadBenchmarkFromUrlSilent(benchPath);
  try {
    await autoLoadInputMixWaveform(compareState.artifact);
  } catch {
    /* optional input lane */
  }
}

function artifactQueryPathFromApiResponse(artifactPath) {
  const raw = String(artifactPath || '').trim().replace(/\\/g, '/');
  if (!raw) {
    return '';
  }
  const withSlash = raw.startsWith('/') ? raw : `/${raw}`;
  return `/ui/compare/?artifact=${encodeURIComponent(withSlash)}`;
}

async function runUploadSeparation() {
  const file = elements.uploadFile.files?.[0];
  if (!file) {
    return;
  }
  elements.uploadSeparateBtn.disabled = true;
  elements.uploadStatusLine.textContent = 'Separating…';
  try {
    const form = new FormData();
    form.append('file', file);
    form.append('device', elements.uploadDevice.value);
    const resp = await fetch('/api/separate', { method: 'POST', body: form });
    const result = await resp.json();
    if (!resp.ok) {
      setBanner(`Upload separation failed: ${result.error ?? resp.statusText}`, { type: 'error' });
      elements.uploadStatusLine.textContent = 'Separation failed.';
      return;
    }
    const next = artifactQueryPathFromApiResponse(result.artifact_path);
    if (next) {
      window.location.assign(next);
      return;
    }
    setBanner('Separation succeeded but server did not return artifact_path.', { type: 'error' });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    setBanner(`Upload separation request failed: ${msg}`, { type: 'error' });
    elements.uploadStatusLine.textContent = 'Request failed.';
  } finally {
    elements.uploadSeparateBtn.disabled = false;
  }
}

function setupUploadControls() {
  elements.uploadFile.addEventListener('change', () => {
    const f = elements.uploadFile.files?.[0];
    elements.uploadSeparateBtn.disabled = !f;
    elements.uploadStatusLine.textContent = f ? `Selected: ${f.name}` : 'Awaiting file…';
  });
  elements.uploadSeparateBtn.addEventListener('click', () => void runUploadSeparation());
}

function stemKeyForFile(file) {
  const name = file.name.toLowerCase();
  return ['vocals', 'drums', 'bass', 'other'].find((stem) => name.includes(stem)) || null;
}

async function loadAudioWaveforms() {
  const inputFile = elements.inputAudioFile.files?.[0];
  const stemFiles = Array.from(elements.stemAudioFiles.files || []);
  if (!inputFile || stemFiles.length < 4) {
    setBanner('Load one input WAV and four stem WAV files.', { type: 'error' });
    return;
  }

  try {
    const inputSamples = decodePcmWav(await inputFile.arrayBuffer());
    drawWaveform(elements.waveformCanvases.input, inputSamples);
    drawSpectrogram(elements.spectrogramCanvases.input, inputSamples);

    const stemsByKey = {};
    stemFiles.forEach((file) => {
      const key = stemKeyForFile(file);
      if (key) {
        stemsByKey[key] = file;
      }
    });

    for (const key of ['vocals', 'drums', 'bass', 'other']) {
      if (!stemsByKey[key]) {
        throw new Error(`Missing ${key}.wav stem file`);
      }
      const samples = decodePcmWav(await stemsByKey[key].arrayBuffer());
      drawWaveform(elements.waveformCanvases[key], samples);
      drawSpectrogram(elements.spectrogramCanvases[key], samples);
    }

    detachCompareAudioPlayback();
    registerBlobLaneUrl('input', URL.createObjectURL(inputFile));
    for (const key of ['vocals', 'drums', 'bass', 'other']) {
      registerBlobLaneUrl(key, URL.createObjectURL(stemsByKey[key]));
    }

    setText(elements.audioFileCount, `${1 + stemFiles.length} files`);
    setBanner(`Loaded WAV assets for waveform inspection.`, { type: 'status' });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setBanner(`Failed to load WAV assets: ${message}`, { type: 'error' });
  }
}

/** Map absolute or repo-relative stem path strings to a fetchable URL path on the demo server. */
function stemPathToRepoUrlPath(stemPath) {
  const raw = typeof stemPath === 'string' ? stemPath.trim() : '';
  if (!raw) {
    throw new Error('stem path is empty');
  }
  let normalized = raw.replace(/\\/g, '/');
  const lower = normalized.toLowerCase();
  const marker = 'artifacts/';
  const idx = lower.indexOf(marker);
  if (idx >= 0) {
    normalized = normalized.slice(idx);
  }
  const segments = normalized.split('/').filter(Boolean);
  if (segments.length === 0) {
    throw new Error('stem path could not be resolved under artifacts/');
  }
  return `/${segments.map((s) => encodeURIComponent(s)).join('/')}`;
}

async function fetchWavArrayBuffer(repoUrlPath) {
  const resolvedUrl = new URL(repoUrlPath, `${window.location.origin}/`);
  if (resolvedUrl.origin !== window.location.origin) {
    throw new Error('stem URL must stay on the same origin');
  }
  const response = await fetch(resolvedUrl.toString(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`WAV fetch failed with status ${response.status}`);
  }
  return response.arrayBuffer();
}

/**
 * Load the four stem WAVs from artifact.stems (paths as emitted by the live runtime).
 * Dual compare callers pass **`artifact2`** so shared lanes visualize the accelerated GPU run;
 * summaries + Input auto-load (`finishPreloadExtras`) still key off **`compareState.artifact`** (primary CPU).
 */
async function autoLoadStemWaveformsFromArtifact(artifact) {
  if (!artifact || !artifact.stems) {
    return { ok: false, message: 'no stem metadata' };
  }
  for (const key of ['vocals', 'drums', 'bass', 'other']) {
    const urlPath = stemPathToRepoUrlPath(artifact.stems[key]);
    const buf = await fetchWavArrayBuffer(urlPath);
    const samples = decodePcmWav(buf);
    drawWaveform(elements.waveformCanvases[key], samples);
    drawSpectrogram(elements.spectrogramCanvases[key], samples);
    registerLaneUrl(key, playbackUrlFromRepoPath(artifact.stems[key]));
  }
  const secondaryStemLabel = compareState.artifact2
    ? deviceLabelForArtifact(compareState.artifact2, 'GPU')
    : null;
  const laneLabel = secondaryStemLabel ? `4 stems (${secondaryStemLabel} auto)` : '4 stems (auto)';
  setText(elements.audioFileCount, laneLabel);
  return { ok: true, message: '' };
}

function toggleLanePlayback(lane) {
  const url = compareState.laneUrls[lane];
  if (!url) {
    setBanner(`No ${lane} audio loaded for playback.`, { type: 'error' });
    return;
  }
  const audio = compareState.audioElement;
  if (compareState.activeLaneKey === lane && audio && !audio.paused) {
    audio.pause();
    updatePausedLaneUi(lane);
    return;
  }
  if (compareState.activeLaneKey === lane && audio && audio.paused) {
    audio
      .play()
      .then(() => updatePlayingLaneUi(lane))
      .catch((err) => {
        setBanner(`Playback failed: ${err.message}`, { type: 'error' });
      });
    return;
  }
  if (audio) {
    audio.pause();
  }
  compareState.audioElement = new Audio(url);
  compareState.activeLaneKey = lane;
  attachPlaybackEndedHandler(compareState.audioElement);
  compareState.audioElement
    .play()
    .then(() => updatePlayingLaneUi(lane))
    .catch((err) => {
      setBanner(`Playback failed: ${err.message}`, { type: 'error' });
      compareState.audioElement = null;
      compareState.activeLaneKey = null;
      setPlaybackUiStopped();
    });
}

function togglePlayback() {
  toggleLanePlayback('input');
}

function normalizeStageTimings(stageTimingsSource, stages) {
  if (stageTimingsSource === null || stageTimingsSource === undefined) {
    return {};
  }

  if (Array.isArray(stageTimingsSource)) {
    const timings = {};
    stageTimingsSource.forEach((entry, index) => {
      if (entry === null || entry === undefined) {
        return;
      }
      if (typeof entry !== 'number' || !Number.isFinite(entry)) {
        throw new Error(`metadata.stage_timings[${index}] must be a finite number`);
      }
      const stageName = stages[index];
      if (stageName) {
        timings[stageName] = entry;
      }
    });
    return timings;
  }

  if (typeof stageTimingsSource === 'object') {
    const timings = {};
    for (const [stageName, value] of Object.entries(stageTimingsSource)) {
      if (typeof value !== 'number' || !Number.isFinite(value)) {
        throw new Error(`metadata.stage_timings.${stageName} must be a finite number`);
      }
      timings[stageName] = value;
    }
    return timings;
  }

  throw new Error('metadata.stage_timings must be an array, object, or null');
}

function normalizeStemPaths(stemPaths) {
  const objectValue = expectObject(stemPaths, 'stem_paths');
  const keys = Object.keys(objectValue).sort();
  const expectedKeys = ['bass', 'drums', 'other', 'vocals'];
  const unexpectedKeys = keys.filter((key) => !expectedKeys.includes(key));
  const missingKeys = expectedKeys.filter((key) => !(key in objectValue));

  if (unexpectedKeys.length > 0 || missingKeys.length > 0) {
    const details = [];
    if (unexpectedKeys.length > 0) {
      details.push(`unexpected keys: ${unexpectedKeys.join(', ')}`);
    }
    if (missingKeys.length > 0) {
      details.push(`missing keys: ${missingKeys.join(', ')}`);
    }
    throw new Error(`stem_paths must contain exactly vocals, drums, bass, and other (${details.join('; ')})`);
  }

  return {
    vocals: expectString(objectValue.vocals, 'stem_paths.vocals'),
    drums: expectString(objectValue.drums, 'stem_paths.drums'),
    bass: expectString(objectValue.bass, 'stem_paths.bass'),
    other: expectString(objectValue.other, 'stem_paths.other'),
  };
}

function deriveSourceLabel(sourceKind, sourceMetadata) {
  const explicitLabel = sourceMetadata.source_label || sourceMetadata.sourceLabel;
  if (typeof explicitLabel === 'string' && explicitLabel.trim()) {
    return explicitLabel.trim();
  }

  if (String(sourceKind).toLowerCase().includes('video')) {
    return 'audio-first extraction from video source';
  }

  return 'native audio source';
}

function buildStageDetails(stages, stageTimings) {
  return stages.map((stage, index) => {
    const lowerStage = stage.toLowerCase();
    return {
      index,
      stage,
      timing: typeof stageTimings[stage] === 'number' ? stageTimings[stage] : null,
      note: STAGE_NOTES[lowerStage] || 'Showcase stage preserved from the loaded artifact.',
    };
  });
}

function deviceLabelForArtifact(artifact, fallbackLabel) {
  const deviceUsed = String(artifact.provenance.deviceUsed || '').toLowerCase();
  if (deviceUsed.startsWith('cpu')) {
    return 'CPU';
  }
  if (deviceUsed.startsWith('gpu') || deviceUsed.includes('cuda')) {
    return 'GPU';
  }
  return fallbackLabel;
}

function formatTotalTiming(totalMs) {
  return `${totalMs.toFixed(2)} ms total`;
}

function formatSpeedup(referenceArtifact, comparisonArtifact) {
  if (comparisonArtifact.timing.total <= 0) {
    return 'Speedup unavailable';
  }

  const speedup = referenceArtifact.timing.total / comparisonArtifact.timing.total;
  return `GPU is ${speedup.toFixed(1)}× faster`;
}

function updateArtifactSummaryPanels(artifact) {
  compareState.artifact = artifact;
  compareState.artifactToken = `${artifact.loadedPath} :: ${artifact.timestamp ?? '—'}`;
  setBanner(`Loaded ${artifact.loadedPath} — source ${artifact.source.kind} (${artifact.source.reference})`, {
    type: 'status',
  });
  setText(elements.selectedFile, `Loaded file: ${artifact.loadedPath}`);
  setText(elements.sourceKind, artifact.source.kind);
  setText(elements.sourceLabel, artifact.source.label);
  setText(elements.sourceReference, artifact.source.reference);
  setText(elements.sourceMetadata, JSON.stringify(artifact.source.metadata, null, 2) || '—');
  setText(elements.artifactPath, artifact.loadedPath);

  setText(elements.compareMode, compareState.activeMode);
  setText(elements.compareModeTitle, MODE_CONFIG[compareState.activeMode].title);
  setText(elements.compareModeDescription, MODE_CONFIG[compareState.activeMode].description);
  setText(elements.compareToken, compareState.artifactToken);
  setStateValue(elements.compareHealth, artifact.health.state);
  setText(elements.runtimeHealthText, `${artifact.health.state} — ${artifact.health.reason}`);
  setText(elements.runtimeSourceText, artifact.source.label);

  setStateValue(elements.healthState, artifact.health.state);
  setText(elements.healthReason, artifact.health.reason);
  setText(elements.requestedModelPath, artifact.health.requestedModelPath);
  setText(elements.modelPath, artifact.health.modelPath);
  setText(elements.fallbackApplied, artifact.health.fallbackApplied ? 'Yes' : 'No');

  setText(elements.timingStft, `${artifact.timing.stft.toFixed(2)} ms`);
  setText(elements.timingInfer, `${artifact.timing.infer.toFixed(2)} ms`);
  setText(elements.timingIstft, `${artifact.timing.istft.toFixed(2)} ms`);
  setText(elements.timingTotal, `${artifact.timing.total.toFixed(2)} ms`);
  setText(elements.timingChunk, `${artifact.timing.chunk.toFixed(2)} s`);
  setText(elements.sampleRate, `${artifact.timing.sampleRate.toLocaleString()} Hz`);

  setText(elements.stemVocals, artifact.stems.vocals);
  setText(elements.stemDrums, artifact.stems.drums);
  setText(elements.stemBass, artifact.stems.bass);
  setText(elements.stemOther, artifact.stems.other);
  setText(elements.queueDepth, String(artifact.stems.queueDepth));
  setText(elements.dropCount, String(artifact.stems.dropCount));

  setText(elements.inputPath, artifact.provenance.input);
  setText(elements.status, artifact.provenance.status);
  setText(elements.timestamp, artifact.provenance.timestamp);
  setText(elements.chunkIndex, String(artifact.provenance.chunkIndex));
  setText(elements.deviceRequested, artifact.provenance.deviceRequested);
  setText(elements.deviceUsed, artifact.provenance.deviceUsed);
  setText(elements.mode, artifact.provenance.mode);
  setText(elements.clockSource, artifact.provenance.clockSource);
  setText(elements.clockFallback, artifact.provenance.clockFallback ? 'Yes' : 'No');
  setText(elements.samplesProcessed, artifact.provenance.samplesProcessed.toLocaleString());
  setText(elements.channels, String(artifact.provenance.channels));
  setText(elements.sampleWidth, `${artifact.provenance.sampleWidth} byte${artifact.provenance.sampleWidth === 1 ? '' : 's'}`);
  renderStages(artifact.provenance.stages, artifact.provenance.stageTimings);
  syncModeButtons();
}

function setDualCompareVisibility(isDual) {
  elements.compareDualBoard.classList.toggle('is-hidden', !isDual);
  elements.stageBoard.classList.toggle('is-hidden', isDual);
  elements.finalStemsStrip.classList.toggle('is-hidden', isDual);
}

function renderArtifactColumn(artifact, roleLabel) {
  const column = document.createElement('article');
  column.className = 'compare-dual-column';
  column.dataset.role = roleLabel.toLowerCase();
  column.dataset.testid = 'compare-dual-column';
  column.innerHTML = `
    <header class="compare-dual-column-header">
      <p class="compare-card-label">${roleLabel}</p>
      <h4>${artifact.source.kind}</h4>
      <p class="compare-dual-column-subtitle">${artifact.source.label}</p>
      <dl class="compare-dual-column-metrics">
        <div>
          <dt>Total</dt>
          <dd>${formatTotalTiming(artifact.timing.total)}</dd>
        </div>
        <div>
          <dt>Health</dt>
          <dd>${artifact.health.state}</dd>
        </div>
        <div>
          <dt>Device</dt>
          <dd>${artifact.provenance.deviceUsed}</dd>
        </div>
        <div>
          <dt>Stages</dt>
          <dd>${artifact.compare.stageDetails.length}</dd>
        </div>
      </dl>
    </header>
  `;

  const stageShell = document.createElement('div');
  stageShell.className = `compare-stage-shell compare-stage-shell--${compareState.activeMode} compare-stage-shell--compact`;
  if (compareState.activeMode === 'side-by-side') {
    stageShell.appendChild(buildStageGrid(artifact.compare.stageDetails));
  } else if (compareState.activeMode === 'overlay') {
    stageShell.appendChild(buildOverlayStageStack(artifact.compare.stageDetails));
  } else {
    stageShell.appendChild(buildTimelineStageList(artifact.compare.stageDetails));
  }
  column.appendChild(stageShell);

  const stemsCard = document.createElement('section');
  stemsCard.className = 'compare-stems-card compare-stems-card--compact';
  stemsCard.innerHTML = `
    <div class="compare-stems-copy">
      <p class="compare-card-label">${roleLabel} stems</p>
      <h3>${artifact.source.kind === 'video-audio' ? 'Audio-first extraction' : 'Final separation outputs'}</h3>
      <p>${[
        `Vocals: ${artifact.stems.vocals}`,
        `Drums: ${artifact.stems.drums}`,
        `Bass: ${artifact.stems.bass}`,
        `Other: ${artifact.stems.other}`,
        `Queue depth: ${artifact.stems.queueDepth}`,
        `Drop count: ${artifact.stems.dropCount}`,
      ].join(' • ')}</p>
    </div>
  `;
  column.appendChild(stemsCard);
  return column;
}

function renderDualComparison(primaryArtifact, secondaryArtifact) {
  const leftArtifact = deviceLabelForArtifact(primaryArtifact, 'CPU') === 'CPU' ? primaryArtifact : secondaryArtifact;
  const rightArtifact = deviceLabelForArtifact(secondaryArtifact, 'GPU') === 'GPU' ? secondaryArtifact : primaryArtifact;
  const primaryLabel = deviceLabelForArtifact(leftArtifact, 'CPU');
  const secondaryLabel = deviceLabelForArtifact(rightArtifact, 'GPU');

  compareState.artifact = leftArtifact;
  compareState.artifact2 = rightArtifact;
  compareState.artifactToken = `${leftArtifact.loadedPath} :: ${leftArtifact.timestamp ?? '—'}`;
  compareState.artifactToken2 = `${rightArtifact.loadedPath} :: ${rightArtifact.timestamp ?? '—'}`;

  setBanner(
    `Loaded comparison artifacts: ${leftArtifact.loadedPath} (${primaryLabel}) and ${rightArtifact.loadedPath} (${secondaryLabel}).`,
    { type: 'status' },
  );
  setText(elements.selectedFile, `Loaded files: ${leftArtifact.loadedPath} vs ${rightArtifact.loadedPath}`);
  setText(elements.sourceKind, `${primaryLabel} / ${secondaryLabel}`);
  setText(elements.sourceLabel, `${leftArtifact.source.label} vs ${rightArtifact.source.label}`);
  setText(elements.sourceReference, `${leftArtifact.source.reference} vs ${rightArtifact.source.reference}`);
  setText(elements.sourceMetadata, 'Comparison mode renders both artifacts in parallel.');
  setText(elements.artifactPath, `${leftArtifact.loadedPath} vs ${rightArtifact.loadedPath}`);

  setText(elements.compareMode, `${compareState.activeMode} + compare`);
  setText(elements.compareModeTitle, 'Dual artifact compare');
  setText(elements.compareModeDescription, 'CPU and GPU artifacts are rendered in parallel for timing comparison.');
  setText(elements.compareToken, `${compareState.artifactToken} | ${compareState.artifactToken2}`);
  setStateValue(elements.compareHealth, leftArtifact.health.state === rightArtifact.health.state ? leftArtifact.health.state : 'degraded');
  setText(elements.runtimeHealthText, `${leftArtifact.health.state} — ${leftArtifact.health.reason} | ${rightArtifact.health.state} — ${rightArtifact.health.reason}`);
  setText(elements.runtimeSourceText, `${primaryLabel} vs ${secondaryLabel}`);

  setStateValue(elements.healthState, leftArtifact.health.state);
  setText(elements.healthReason, `${leftArtifact.health.reason} / ${rightArtifact.health.reason}`);
  setText(elements.requestedModelPath, `${leftArtifact.health.requestedModelPath} / ${rightArtifact.health.requestedModelPath}`);
  setText(elements.modelPath, `${leftArtifact.health.modelPath} / ${rightArtifact.health.modelPath}`);
  setText(elements.fallbackApplied, `${leftArtifact.health.fallbackApplied ? 'CPU yes' : 'CPU no'} / ${rightArtifact.health.fallbackApplied ? 'GPU yes' : 'GPU no'}`);

  setText(elements.timingStft, `${leftArtifact.timing.stft.toFixed(2)} ms / ${rightArtifact.timing.stft.toFixed(2)} ms`);
  setText(elements.timingInfer, `${leftArtifact.timing.infer.toFixed(2)} ms / ${rightArtifact.timing.infer.toFixed(2)} ms`);
  setText(elements.timingIstft, `${leftArtifact.timing.istft.toFixed(2)} ms / ${rightArtifact.timing.istft.toFixed(2)} ms`);
  setText(elements.timingTotal, `${leftArtifact.timing.total.toFixed(2)} ms / ${rightArtifact.timing.total.toFixed(2)} ms`);
  setText(elements.timingChunk, `${leftArtifact.timing.chunk.toFixed(2)} s / ${rightArtifact.timing.chunk.toFixed(2)} s`);
  setText(elements.sampleRate, `${leftArtifact.timing.sampleRate.toLocaleString()} Hz / ${rightArtifact.timing.sampleRate.toLocaleString()} Hz`);

  setText(elements.stemVocals, `${leftArtifact.stems.vocals} / ${rightArtifact.stems.vocals}`);
  setText(elements.stemDrums, `${leftArtifact.stems.drums} / ${rightArtifact.stems.drums}`);
  setText(elements.stemBass, `${leftArtifact.stems.bass} / ${rightArtifact.stems.bass}`);
  setText(elements.stemOther, `${leftArtifact.stems.other} / ${rightArtifact.stems.other}`);
  setText(elements.queueDepth, `${leftArtifact.stems.queueDepth} / ${rightArtifact.stems.queueDepth}`);
  setText(elements.dropCount, `${leftArtifact.stems.dropCount} / ${rightArtifact.stems.dropCount}`);

  setText(elements.inputPath, `${leftArtifact.provenance.input} / ${rightArtifact.provenance.input}`);
  setText(elements.status, `${leftArtifact.provenance.status} / ${rightArtifact.provenance.status}`);
  setText(elements.timestamp, `${leftArtifact.provenance.timestamp} / ${rightArtifact.provenance.timestamp}`);
  setText(elements.chunkIndex, `${leftArtifact.provenance.chunkIndex} / ${rightArtifact.provenance.chunkIndex}`);
  setText(elements.deviceRequested, `${leftArtifact.provenance.deviceRequested} / ${rightArtifact.provenance.deviceRequested}`);
  setText(elements.deviceUsed, `${leftArtifact.provenance.deviceUsed} / ${rightArtifact.provenance.deviceUsed}`);
  setText(elements.mode, `${leftArtifact.provenance.mode} / ${rightArtifact.provenance.mode}`);
  setText(elements.clockSource, `${leftArtifact.provenance.clockSource} / ${rightArtifact.provenance.clockSource}`);
  setText(elements.clockFallback, `${leftArtifact.provenance.clockFallback ? 'Yes' : 'No'} / ${rightArtifact.provenance.clockFallback ? 'Yes' : 'No'}`);
  setText(elements.samplesProcessed, `${leftArtifact.provenance.samplesProcessed.toLocaleString()} / ${rightArtifact.provenance.samplesProcessed.toLocaleString()}`);
  setText(elements.channels, `${leftArtifact.provenance.channels} / ${rightArtifact.provenance.channels}`);
  setText(elements.sampleWidth, `${leftArtifact.provenance.sampleWidth} / ${rightArtifact.provenance.sampleWidth} bytes`);

  setDualCompareVisibility(true);
  elements.compareDualLeftRole.textContent = primaryLabel;
  elements.compareDualLeftTotal.textContent = formatTotalTiming(leftArtifact.timing.total);
  elements.compareDualRightRole.textContent = secondaryLabel;
  elements.compareDualRightTotal.textContent = formatTotalTiming(rightArtifact.timing.total);
  elements.compareDualSpeedup.textContent = formatSpeedup(leftArtifact, rightArtifact);

  elements.compareDualColumns.innerHTML = '';
  elements.compareDualColumns.appendChild(renderArtifactColumn(leftArtifact, primaryLabel));
  elements.compareDualColumns.appendChild(renderArtifactColumn(rightArtifact, secondaryLabel));

  setText(elements.finalStemsLabel, 'Comparison stems');
  setText(elements.finalStemsDetails, `${primaryLabel}: ${formatTotalTiming(leftArtifact.timing.total)} | ${secondaryLabel}: ${formatTotalTiming(rightArtifact.timing.total)} | ${formatSpeedup(leftArtifact, rightArtifact)}`);
  syncModeButtons();
  compareState.lastModeMessage = `Loaded ${leftArtifact.loadedPath} and ${rightArtifact.loadedPath} in ${compareState.activeMode} mode.`;
}

function normalizeArtifact(payload, loadedPath) {
  const root = expectObject(payload, 'Artifact root');
  const source = expectObject(root.source, 'source');
  const metadata = expectObject(root.metadata, 'metadata');
  const stemPaths = normalizeStemPaths(root.stem_paths);

  const sourceMetadata = source.metadata && typeof source.metadata === 'object' && !Array.isArray(source.metadata)
    ? source.metadata
    : {};

  const stages = Array.isArray(metadata.stages) ? metadata.stages.map((stage, index) => expectString(stage, `metadata.stages[${index}]`)) : null;
  if (!stages || stages.length === 0) {
    throw new Error('metadata.stages must contain at least one stage');
  }

  const stageTimings = normalizeStageTimings(metadata.stage_timings ?? root.stage_timings ?? null, stages);
  const rootStft = expectNumber(root.stft_ms, 'stft_ms');
  const rootInfer = expectNumber(root.infer_ms, 'infer_ms');
  const rootIstft = expectNumber(root.istft_ms, 'istft_ms');
  const filledStageTimings = {};
  for (const s of stages) {
    const v = stageTimings[s];
    if (typeof v === 'number' && Number.isFinite(v)) {
      filledStageTimings[s] = v;
    } else if (s === 'stft') {
      filledStageTimings[s] = rootStft;
    } else if (s === 'infer') {
      filledStageTimings[s] = rootInfer;
    } else if (s === 'istft') {
      filledStageTimings[s] = rootIstft;
    }
  }
  const sourceKind = expectString(source.kind, 'source.kind');
  const sourceReference = expectString(source.reference, 'source.reference');
  const input = expectString(root.input, 'input');
  const timestamp = expectString(root.timestamp, 'timestamp');
  const healthState = expectString(root.health_state, 'health_state');
  const healthReason = expectString(root.health_reason, 'health_reason');
  const requestedModelPath = expectString(root.requested_model_path, 'requested_model_path');
  const modelPath = expectString(root.model_path, 'model_path');
  const status = expectString(root.status, 'status');
  const artifact = {
    loadedPath,
    source: {
      kind: sourceKind,
      label: deriveSourceLabel(sourceKind, sourceMetadata),
      reference: sourceReference,
      metadata: sourceMetadata,
    },
    health: {
      state: healthState,
      reason: healthReason,
      requestedModelPath,
      modelPath,
      fallbackApplied: expectBoolean(root.fallback_applied, 'fallback_applied'),
    },
    timing: {
      stft: expectNumber(root.stft_ms, 'stft_ms'),
      infer: expectNumber(root.infer_ms, 'infer_ms'),
      istft: expectNumber(root.istft_ms, 'istft_ms'),
      total: expectNumber(root.total_ms, 'total_ms'),
      chunk: expectNumber(root.chunk_duration_s, 'chunk_duration_s'),
      sampleRate: expectInteger(root.sample_rate_hz, 'sample_rate_hz', { min: 8000 }),
    },
    stems: {
      vocals: stemPaths.vocals,
      drums: stemPaths.drums,
      bass: stemPaths.bass,
      other: stemPaths.other,
      queueDepth: expectInteger(root.queue_depth, 'queue_depth', { min: 0 }),
      dropCount: expectInteger(root.drop_count, 'drop_count', { min: 0 }),
    },
    provenance: {
      input,
      status,
      timestamp,
      chunkIndex: expectInteger(root.chunk_index, 'chunk_index', { min: 0 }),
      deviceRequested: expectString(metadata.device_requested, 'metadata.device_requested'),
      deviceUsed: expectString(metadata.device_used, 'metadata.device_used'),
      mode: expectString(metadata.mode, 'metadata.mode'),
      clockSource: expectString(metadata.clock_source, 'metadata.clock_source'),
      clockFallback: expectBoolean(metadata.clock_fallback, 'metadata.clock_fallback'),
      samplesProcessed: expectInteger(metadata.samples_processed, 'metadata.samples_processed', { min: 0 }),
      channels: expectInteger(metadata.channels, 'metadata.channels', { min: 0 }),
      sampleWidth: expectInteger(metadata.sample_width_bytes, 'metadata.sample_width_bytes', { min: 0 }),
      stages,
      stageTimings: filledStageTimings,
      errorStage: root.error_stage === null || root.error_stage === undefined ? null : expectString(root.error_stage, 'error_stage'),
      errorMessage: root.error_message === null || root.error_message === undefined ? null : expectString(root.error_message, 'error_message'),
    },
    compare: {
      stageDetails: buildStageDetails(stages, filledStageTimings),
      sourceSummary: deriveSourceLabel(sourceKind, sourceMetadata),
    },
  };

  const allowedStatus = new Set(['ok', 'error']);
  const allowedHealth = new Set(['healthy', 'degraded', 'fallback']);
  if (!allowedStatus.has(artifact.provenance.status)) {
    throw new Error(`status must be one of: ${Array.from(allowedStatus).join(', ')}`);
  }
  if (!allowedHealth.has(artifact.health.state)) {
    throw new Error(`health_state must be one of: ${Array.from(allowedHealth).join(', ')}`);
  }

  return artifact;
}

function renderArtifact(artifact) {
  compareState.artifact2 = null;
  compareState.artifactToken2 = '—';
  setDualCompareVisibility(false);
  updateArtifactSummaryPanels(artifact);
  renderCompareCanvas(artifact);
  compareState.lastModeMessage = `Loaded ${artifact.loadedPath} in ${compareState.activeMode} mode.`;
}

function renderCompareCanvas(artifact = compareState.artifact) {
  const config = MODE_CONFIG[compareState.activeMode];
  elements.compareCanvas.dataset.mode = compareState.activeMode;
  const isDual = Boolean(compareState.artifact && compareState.artifact2);
  elements.compareCanvas.dataset.hasArtifact = artifact ? 'true' : 'false';
  elements.compareCanvas.dataset.layout = isDual ? 'dual' : compareState.activeMode;
  setText(elements.stageBoardCaption, artifact
    ? (isDual
      ? 'CPU and GPU artifacts are shown through the same compare mode.'
      : `The same loaded artifact is shown through the ${config.title.toLowerCase()} layout.`)
    : 'Load an artifact to compare the fixed stage showcase.');

  if (!artifact) {
    setDualCompareVisibility(false);
    elements.stageBoard.innerHTML = `
      <div class="compare-empty-state" data-testid="compare-empty-state">
        <p>No artifact loaded yet.</p>
        <p>Select a JSON file to reveal the stage showcase, final stems, and runtime metadata.</p>
      </div>
    `;
    elements.compareDualColumns.innerHTML = '';
    elements.compareDualLeftRole.textContent = 'CPU';
    elements.compareDualLeftTotal.textContent = '—';
    elements.compareDualRightRole.textContent = 'GPU';
    elements.compareDualRightTotal.textContent = '—';
    elements.compareDualSpeedup.textContent = '—';
    setText(elements.finalStemsLabel, 'Final stems');
    setText(elements.finalStemsDetails, 'Waiting on a loaded artifact.');
    return;
  }

  if (isDual) {
    setDualCompareVisibility(true);
    elements.stageBoard.innerHTML = '';
    elements.compareDualColumns.innerHTML = '';
    elements.compareDualColumns.appendChild(renderArtifactColumn(compareState.artifact, deviceLabelForArtifact(compareState.artifact, 'CPU')));
    elements.compareDualColumns.appendChild(renderArtifactColumn(compareState.artifact2, deviceLabelForArtifact(compareState.artifact2, 'GPU')));
    elements.compareDualLeftRole.textContent = deviceLabelForArtifact(compareState.artifact, 'CPU');
    elements.compareDualLeftTotal.textContent = formatTotalTiming(compareState.artifact.timing.total);
    elements.compareDualRightRole.textContent = deviceLabelForArtifact(compareState.artifact2, 'GPU');
    elements.compareDualRightTotal.textContent = formatTotalTiming(compareState.artifact2.timing.total);
    elements.compareDualSpeedup.textContent = formatSpeedup(compareState.artifact, compareState.artifact2);
    setText(elements.finalStemsLabel, 'Comparison stems');
    setText(elements.finalStemsDetails, `${deviceLabelForArtifact(compareState.artifact, 'CPU')}: ${formatTotalTiming(compareState.artifact.timing.total)} | ${deviceLabelForArtifact(compareState.artifact2, 'GPU')}: ${formatTotalTiming(compareState.artifact2.timing.total)} | ${formatSpeedup(compareState.artifact, compareState.artifact2)}`);
    return;
  }

  const stages = artifact.compare.stageDetails;
  const stemSummary = [
    `Vocals: ${artifact.stems.vocals}`,
    `Drums: ${artifact.stems.drums}`,
    `Bass: ${artifact.stems.bass}`,
    `Other: ${artifact.stems.other}`,
    `Queue depth: ${artifact.stems.queueDepth}`,
    `Drop count: ${artifact.stems.dropCount}`,
  ].join(' • ');

  elements.stageBoard.innerHTML = '';
  const modeShell = document.createElement('div');
  modeShell.className = `compare-stage-shell compare-stage-shell--${compareState.activeMode}`;
  modeShell.dataset.testid = `compare-stage-shell-${compareState.activeMode}`;

  if (compareState.activeMode === 'side-by-side') {
    modeShell.appendChild(buildStageGrid(stages));
  } else if (compareState.activeMode === 'overlay') {
    modeShell.appendChild(buildOverlayStageStack(stages));
  } else {
    modeShell.appendChild(buildTimelineStageList(stages));
  }

  const stemsCard = document.createElement('section');
  stemsCard.className = 'compare-stems-card';
  stemsCard.innerHTML = `
    <div class="compare-stems-copy">
      <p class="compare-card-label">Final stems</p>
      <h3>${artifact.source.kind === 'video-audio' ? 'Audio-first extraction' : 'Final separation outputs'}</h3>
      <p>${stemSummary}</p>
    </div>
    <dl class="compare-stems-list" data-testid="compare-stems-list">
      <div>
        <dt>Vocals</dt>
        <dd>${artifact.stems.vocals}</dd>
      </div>
      <div>
        <dt>Drums</dt>
        <dd>${artifact.stems.drums}</dd>
      </div>
      <div>
        <dt>Bass</dt>
        <dd>${artifact.stems.bass}</dd>
      </div>
      <div>
        <dt>Other</dt>
        <dd>${artifact.stems.other}</dd>
      </div>
      <div>
        <dt>Queue depth</dt>
        <dd>${artifact.stems.queueDepth}</dd>
      </div>
      <div>
        <dt>Drop count</dt>
        <dd>${artifact.stems.dropCount}</dd>
      </div>
    </dl>
  `;

  modeShell.appendChild(stemsCard);
  elements.stageBoard.appendChild(modeShell);
  setText(elements.finalStemsLabel, artifact.source.kind === 'video-audio' ? 'Audio-first extraction' : 'Final stems');
  setText(elements.finalStemsDetails, stemSummary);
}

function buildStageCard(stageDetail, { compact = false } = {}) {
  const article = document.createElement('article');
  article.className = `stage-card stage-card--${compareState.activeMode}`;
  article.dataset.stage = stageDetail.stage;
  article.dataset.index = String(stageDetail.index);
  article.dataset.testid = 'compare-stage-card';
  article.style.setProperty('--stage-index', String(stageDetail.index));
  article.innerHTML = `
    <div class="stage-card-header">
      <span class="stage-card-index">${String(stageDetail.index + 1).padStart(2, '0')}</span>
      <p class="stage-card-kicker">Fixed showcase stage</p>
    </div>
    <h4>${stageDetail.stage}</h4>
    <p class="stage-card-note">${stageDetail.note}</p>
    <div class="stage-card-meta">
      <span>${stageDetail.timing === null ? 'Timing unavailable' : `${stageDetail.timing.toFixed(2)} ms`}</span>
      <span>${compact ? 'Compact' : 'Comparable'}</span>
    </div>
  `;
  return article;
}

function buildStageGrid(stages) {
  const grid = document.createElement('div');
  grid.className = 'compare-stage-grid';
  grid.dataset.layout = 'side-by-side';
  stages.forEach((stageDetail) => {
    grid.appendChild(buildStageCard(stageDetail));
  });
  return grid;
}

function buildOverlayStageStack(stages) {
  const stack = document.createElement('div');
  stack.className = 'compare-stage-stack';
  stack.dataset.layout = 'overlay';
  stages.forEach((stageDetail, index) => {
    const card = buildStageCard(stageDetail);
    card.style.setProperty('--overlay-offset', `${index * 18}px`);
    card.style.setProperty('--overlay-scale', `${1 - index * 0.045}`);
    card.style.zIndex = String(100 - index);
    stack.appendChild(card);
  });
  return stack;
}

function buildTimelineStageList(stages) {
  const timeline = document.createElement('ol');
  timeline.className = 'compare-stage-timeline';
  timeline.dataset.layout = 'timeline';
  stages.forEach((stageDetail) => {
    const li = document.createElement('li');
    li.className = 'timeline-item';
    li.dataset.stage = stageDetail.stage;
    li.innerHTML = `
      <div class="timeline-rail" aria-hidden="true"></div>
      ${buildStageCard(stageDetail, { compact: true }).outerHTML}
    `;
    timeline.appendChild(li);
  });
  return timeline;
}

function syncModeButtons() {
  elements.compareModeButtons.forEach((button) => {
    const nextMode = button.dataset.mode;
    const isActive = nextMode === compareState.activeMode;
    button.classList.toggle('is-active', isActive);
    button.setAttribute('aria-pressed', String(isActive));
    button.setAttribute('aria-selected', String(isActive));
  });
}

function setCompareMode(nextMode) {
  const normalizedMode = MODE_CONFIG[nextMode] ? nextMode : 'side-by-side';
  const wasInvalid = normalizedMode !== nextMode;
  compareState.activeMode = normalizedMode;
  renderCompareCanvas(compareState.artifact);
  if (compareState.artifact2) {
    setText(elements.compareMode, `${compareState.activeMode} + compare`);
    setText(elements.compareModeTitle, 'Dual artifact compare');
    setText(elements.compareModeDescription, 'CPU and GPU artifacts are rendered in parallel for timing comparison.');
  } else {
    setText(elements.compareMode, compareState.activeMode);
    setText(elements.compareModeTitle, MODE_CONFIG[compareState.activeMode].title);
    setText(elements.compareModeDescription, MODE_CONFIG[compareState.activeMode].description);
  }
  syncModeButtons();
  if (wasInvalid) {
    setBanner(`Unsupported compare mode "${nextMode}" fell back to side-by-side.`, { type: 'error' });
    return;
  }

  if (compareState.artifact2) {
    setBanner(
      `Loaded comparison artifacts in ${compareState.activeMode} mode.`,
      { type: 'status' },
    );
  } else if (compareState.artifact) {
    setBanner(`Loaded ${compareState.artifact.loadedPath} in ${compareState.activeMode} mode.`, { type: 'status' });
  } else {
    setBanner('Awaiting a loaded artifact.', { type: 'status' });
  }
}

async function loadArtifactFromFile() {
  const file = elements.fileInput.files?.[0];
  if (!file) {
    setEmptyState();
    setBanner('Select a JSON artifact before loading.', { type: 'error' });
    return;
  }

  setLoading(true);
  try {
    const raw = await file.text();
    renderArtifact(normalizeArtifact(JSON.parse(raw), file.name));
    setBanner(`Loaded file: ${file.name}`, { type: 'status' });
    try {
      await autoLoadStemWaveformsFromArtifact(compareState.artifact);
    } catch (stemError) {
      const stemMessage = stemError instanceof Error ? stemError.message : String(stemError);
      setBanner(
        `Loaded file: ${file.name}. Stem auto-load failed: ${stemMessage} (use manual WAV loader).`,
        { type: 'status' },
      );
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!compareState.artifact) {
      compareState.artifactToken = '—';
      setEmptyState();
    }
    setBanner(`Failed to parse or validate JSON artifact: ${message}`, { type: 'error' });
  } finally {
    setLoading(false);
  }
}

function resolveArtifactUrl(artifactPath) {
  const normalizedPath = typeof artifactPath === 'string' ? artifactPath.trim() : '';
  if (!normalizedPath) {
    throw new Error('artifact query parameter must be a non-empty path');
  }

  const resolvedUrl = new URL(normalizedPath, `${window.location.origin}/`);
  if (resolvedUrl.origin !== window.location.origin) {
    throw new Error('artifact query parameter must stay on the same local server origin');
  }
  return resolvedUrl;
}

async function loadArtifactFromUrl(artifactPath) {
  compareState.artifact2 = null;
  compareState.artifactToken2 = '—';
  const resolvedUrl = resolveArtifactUrl(artifactPath);
  const loadedPath = resolvedUrl.pathname.replace(/^\/+/, '') || resolvedUrl.pathname;

  setLoading(true);
  try {
    const response = await fetch(resolvedUrl.toString(), { cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`artifact request failed with status ${response.status}`);
    }

    renderArtifact(normalizeArtifact(await response.json(), loadedPath));
    setBanner(`Loaded artifact from URL (${loadedPath}).`, { type: 'status' });
    try {
      await autoLoadStemWaveformsFromArtifact(compareState.artifact);
    } catch (stemError) {
      const stemMessage = stemError instanceof Error ? stemError.message : String(stemError);
      setBanner(
        `Loaded artifact from URL (${loadedPath}). Stem auto-load failed: ${stemMessage} (use manual WAV loader).`,
        { type: 'status' },
      );
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!compareState.artifact) {
      setEmptyState();
    }
    setBanner(`Failed to preload artifact: ${message}`, { type: 'error' });
  } finally {
    setLoading(false);
  }
}

async function loadComparisonFromUrls(artifactPath, artifactPath2) {
  setLoading(true);
  compareState.artifact2 = null;
  compareState.artifactToken2 = '—';
  try {
    const [artifactOne, artifactTwo] = await Promise.all([
      (async () => {
        const resolvedUrl = resolveArtifactUrl(artifactPath);
        const loadedPath = resolvedUrl.pathname.replace(/^\/+/, '') || resolvedUrl.pathname;
        const response = await fetch(resolvedUrl.toString(), { cache: 'no-store' });
        if (!response.ok) {
          throw new Error(`artifact request failed with status ${response.status}`);
        }
        return normalizeArtifact(await response.json(), loadedPath);
      })(),
      (async () => {
        const resolvedUrl = resolveArtifactUrl(artifactPath2);
        const loadedPath = resolvedUrl.pathname.replace(/^\/+/, '') || resolvedUrl.pathname;
        const response = await fetch(resolvedUrl.toString(), { cache: 'no-store' });
        if (!response.ok) {
          throw new Error(`artifact2 request failed with status ${response.status}`);
        }
        return normalizeArtifact(await response.json(), loadedPath);
      })(),
    ]);

    const artifactOneLabel = deviceLabelForArtifact(artifactOne, 'CPU');
    const artifactTwoLabel = deviceLabelForArtifact(artifactTwo, 'GPU');
    const primaryArtifact = artifactOneLabel === 'CPU' ? artifactOne : artifactTwo;
    const secondaryArtifact = artifactTwoLabel === 'GPU' ? artifactTwo : artifactOne;
    const primaryLabel = deviceLabelForArtifact(primaryArtifact, 'CPU');
    const secondaryLabel = deviceLabelForArtifact(secondaryArtifact, 'GPU');

    compareState.artifact = primaryArtifact;
    compareState.artifact2 = secondaryArtifact;
    compareState.artifactToken = `${primaryArtifact.loadedPath} :: ${primaryArtifact.timestamp ?? '—'}`;
    compareState.artifactToken2 = `${secondaryArtifact.loadedPath} :: ${secondaryArtifact.timestamp ?? '—'}`;
    updateArtifactSummaryPanels(primaryArtifact);
    renderCompareCanvas(primaryArtifact);
    let stemNote = '';
    try {
      await autoLoadStemWaveformsFromArtifact(secondaryArtifact);
      stemNote =
        ` Waveform stems: secondary (${secondaryLabel}) run.` +
        ` Input / Play: primary (${primaryLabel}) mix.wav → original input heuristic (finishPreloadExtras).`;
    } catch (stemError) {
      const stemMessage = stemError instanceof Error ? stemError.message : String(stemError);
      stemNote = ` Stem auto-load failed: ${stemMessage} (use manual WAV loader).`;
    }
    setBanner(
      `Loaded comparison artifacts: ${primaryArtifact.loadedPath} (${primaryLabel}) and ${secondaryArtifact.loadedPath} (${secondaryLabel}).${stemNote}`,
      { type: 'status' },
    );
    setText(elements.compareMode, `${compareState.activeMode} + compare`);
    setText(elements.compareModeTitle, 'Dual artifact compare');
    setText(elements.compareModeDescription, 'CPU and GPU artifacts are rendered in parallel for timing comparison.');
    setText(elements.compareToken, `${compareState.artifactToken} | ${compareState.artifactToken2}`);
    setText(elements.runtimeSourceText, `${primaryLabel} vs ${secondaryLabel}`);
    setText(elements.finalStemsLabel, 'Comparison stems');
    setText(elements.finalStemsDetails, `${primaryLabel}: ${formatTotalTiming(primaryArtifact.timing.total)} | ${secondaryLabel}: ${formatTotalTiming(secondaryArtifact.timing.total)} | ${formatSpeedup(primaryArtifact, secondaryArtifact)}`);
    compareState.lastModeMessage = `Loaded ${primaryArtifact.loadedPath} and ${secondaryArtifact.loadedPath} in ${compareState.activeMode} mode.`;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!compareState.artifact) {
      setEmptyState();
    }
    setBanner(`Failed to preload comparison artifacts: ${message}`, { type: 'error' });
  } finally {
    setLoading(false);
  }
}

function handleFileSelection() {
  const file = elements.fileInput.files?.[0];
  elements.selectedFile.textContent = file ? `Selected file: ${file.name}` : 'No file selected';
}

function syncBenchmarkChosenLabel() {
  const file = elements.benchmarkFileInput.files?.[0];
  setText(
    elements.benchmarkSelectedLine,
    file ? `Selected benchmark: ${file.name}` : 'No benchmark JSON selected',
  );
}

async function refreshManualArtifactsFolderStatus() {
  const el = document.getElementById('manual-fs-folder-status');
  if (!el) {
    return;
  }
  if (!isArtifactsScopePickerSupported()) {
    el.textContent = 'Use Chrome / Edge · structured pick targets artifacts/live and artifacts/bench.';
    return;
  }
  const root = await loadPersistedArtifactsRoot();
  if (!root) {
    el.textContent = '(No folder saved)';
    return;
  }
  const readable = await requestDirectoryReadAccess(root);
  if (!readable) {
    el.textContent = 'Saved folder permission expired.';
    await clearPersistedArtifactsRoot();
    return;
  }
  el.textContent = `Saved: "${root.name}"`;
}

function setupManualFilesystemScopes() {
  const inner = document.querySelector('.manual-loaders-inner');
  const rememberBtn = document.getElementById('manual-fs-remember-folder');
  const forgetBtn = document.getElementById('manual-fs-forget-folder');

  rememberBtn?.addEventListener('click', async () => {
    try {
      const handle = await persistArtifactsFolderFromUser();
      setBanner(
        `Remembered “${handle.name}”. “Choose file” uses structured pickers toward artifacts/live and artifacts/bench when present.`,
        { type: 'status' },
      );
      await refreshManualArtifactsFolderStatus();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setBanner(`Could not remember folder: ${message}`, { type: 'error' });
    }
  });

  forgetBtn?.addEventListener('click', async () => {
    await clearPersistedArtifactsRoot();
    setBanner('Cleared remembered artifacts folder.', { type: 'status' });
    await refreshManualArtifactsFolderStatus();
  });

  void refreshManualArtifactsFolderStatus();

  if (!inner || !isArtifactsScopePickerSupported()) {
    return;
  }

  inner.addEventListener('click', async (ev) => {
    const label = ev.target.closest('[data-fs-kind]');
    if (!label) {
      return;
    }
    const rawKind = label.getAttribute('data-fs-kind');
    const allowedKinds = new Set(['artifact', 'benchmark', 'wav-input', 'wav-stems']);
    if (!rawKind || !allowedKinds.has(rawKind)) {
      return;
    }
    ev.preventDefault();
    ev.stopPropagation();
    try {
      await runScopedKindPicker(/** @type {'artifact' | 'benchmark' | 'wav-input' | 'wav-stems'} */ (rawKind), {
        artifact: elements.fileInput,
        benchmark: elements.benchmarkFileInput,
        wavInput: elements.inputAudioFile,
        wavStems: elements.stemAudioFiles,
      });
      if (rawKind === 'benchmark') {
        syncBenchmarkChosenLabel();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setBanner(`Structured file picker failed: ${message}`, { type: 'error' });
    }
  }, true);
}

function initialize() {
  compareState.activeMode = 'side-by-side';
  setEmptyState();
  setEmptyBenchmarkState();
  compareState.benchmarkLoaded = false;
  elements.fileInput.addEventListener('change', handleFileSelection);
  elements.benchmarkFileInput.addEventListener('change', syncBenchmarkChosenLabel);
  elements.loadButton.addEventListener('click', loadArtifactFromFile);
  elements.loadBenchmarkButton.addEventListener('click', loadBenchmarkFromFile);
  elements.loadAudioButton.addEventListener('click', loadAudioWaveforms);
  elements.playbackToggle.addEventListener('click', togglePlayback);
  LANE_PLAY_KEYS.forEach((lane) => {
    lanePlayButton(lane)?.addEventListener('click', () => toggleLanePlayback(lane));
  });
  elements.compareModeButtons.forEach((button) => {
    button.addEventListener('click', () => setCompareMode(button.dataset.mode));
  });
  setupUploadControls();
  setupManualFilesystemScopes();
  void initFromLocation();
}

async function initFromLocation() {
  const params = new URLSearchParams(window.location.search);
  const preloadArtifact = params.get('artifact');
  const preloadArtifact2 = params.get('artifact2');
  const benchmarkQuery = params.get('benchmark');

  if (preloadArtifact2 && !preloadArtifact) {
    setAudienceMode(false);
    setBanner('artifact2 requires an artifact query parameter.', { type: 'error' });
    return;
  }

  if (preloadArtifact) {
    setAudienceMode(true);
    if (preloadArtifact2) {
      await loadComparisonFromUrls(preloadArtifact, preloadArtifact2);
    } else {
      await loadArtifactFromUrl(preloadArtifact);
    }
    if (compareState.artifact) {
      await finishPreloadExtras(benchmarkQuery || '');
    }
    return;
  }

  setAudienceMode(false);
  setBanner('Awaiting a loaded artifact.', { type: 'status' });
}

initialize();
