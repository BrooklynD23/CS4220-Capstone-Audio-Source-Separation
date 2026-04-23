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
  fileInput: document.getElementById('artifact-file'),
  loadButton: document.getElementById('load-button'),
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
  stageBoard: document.getElementById('stage-board'),
  stageBoardCaption: document.getElementById('stage-board-caption'),
  finalStemsLabel: document.getElementById('final-stems-label'),
  finalStemsDetails: document.getElementById('final-stems-details'),
  runtimeHealthText: document.getElementById('runtime-health-text'),
  runtimeSourceText: document.getElementById('runtime-source-text'),
};

const compareState = {
  artifact: null,
  artifactToken: '—',
  activeMode: 'side-by-side',
  lastModeMessage: 'Awaiting a loaded artifact.',
};

window.__compareState = compareState;
window.__setCompareMode = setCompareMode;
window.__loadCompareArtifact = loadArtifactFromFile;

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
      stageTimings,
      errorStage: root.error_stage === null || root.error_stage === undefined ? null : expectString(root.error_stage, 'error_stage'),
      errorMessage: root.error_message === null || root.error_message === undefined ? null : expectString(root.error_message, 'error_message'),
    },
    compare: {
      stageDetails: buildStageDetails(stages, stageTimings),
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
  compareState.artifact = artifact;
  compareState.artifactToken = `${artifact.loadedPath} :: ${artifact.timestamp}`;
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
  renderCompareCanvas(artifact);
  syncModeButtons();
  compareState.lastModeMessage = `Loaded ${artifact.loadedPath} in ${compareState.activeMode} mode.`;
}

function renderCompareCanvas(artifact) {
  const config = MODE_CONFIG[compareState.activeMode];
  elements.compareCanvas.dataset.mode = compareState.activeMode;
  elements.compareCanvas.dataset.hasArtifact = artifact ? 'true' : 'false';
  setText(elements.stageBoardCaption, artifact
    ? `The same loaded artifact is shown through the ${config.title.toLowerCase()} layout.`
    : 'Load an artifact to compare the fixed stage showcase.');

  if (!artifact) {
    elements.stageBoard.innerHTML = `
      <div class="compare-empty-state" data-testid="compare-empty-state">
        <p>No artifact loaded yet.</p>
        <p>Select a JSON file to reveal the stage showcase, final stems, and runtime metadata.</p>
      </div>
    `;
    setText(elements.finalStemsLabel, 'Final stems');
    setText(elements.finalStemsDetails, 'Waiting on a loaded artifact.');
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
  setText(elements.compareMode, compareState.activeMode);
  setText(elements.compareModeTitle, MODE_CONFIG[compareState.activeMode].title);
  setText(elements.compareModeDescription, MODE_CONFIG[compareState.activeMode].description);
  renderCompareCanvas(compareState.artifact);
  syncModeButtons();
  if (wasInvalid) {
    setBanner(`Unsupported compare mode "${nextMode}" fell back to side-by-side.`, { type: 'error' });
    return;
  }

  if (compareState.artifact) {
    setBanner(`Loaded ${compareState.artifact.loadedPath} in ${compareState.activeMode} mode.`, { type: 'status' });
  } else {
    setBanner('Awaiting a loaded artifact.', { type: 'status' });
  }
}

async function loadArtifactFromFile() {
  const file = elements.fileInput.files?.[0];
  if (!file) {
    compareState.artifact = null;
    compareState.artifactToken = '—';
    setEmptyState();
    setBanner('Select a JSON artifact before loading.', { type: 'error' });
    return;
  }

  setLoading(true);
  try {
    const raw = await file.text();
    const payload = JSON.parse(raw);
    const artifact = normalizeArtifact(payload, file.name);
    renderArtifact(artifact);
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

function handleFileSelection() {
  const file = elements.fileInput.files?.[0];
  elements.selectedFile.textContent = file ? `Selected file: ${file.name}` : 'No file selected';
}

function initialize() {
  compareState.activeMode = 'side-by-side';
  setEmptyState();
  elements.fileInput.addEventListener('change', handleFileSelection);
  elements.loadButton.addEventListener('click', loadArtifactFromFile);
  elements.compareModeButtons.forEach((button) => {
    button.addEventListener('click', () => setCompareMode(button.dataset.mode));
  });
  setBanner('Awaiting a loaded artifact.', { type: 'status' });
}

initialize();
