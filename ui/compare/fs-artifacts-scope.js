/**
 * Optional Chromium helper: persisted directory scope + structured file pickers so
 * "Choose file" can start under artifacts/live or artifacts/bench after the user
 * grants once (cannot be automated on plain input[type=file]).
 */

export const ARTIFACT_SCOPE_KEY = 'artifactsDirectoryScope';

const DB_NAME = 'audio_sep_compare_fs_scope';
const DB_VERSION = 1;
const STORE = 'kv';

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error(String(req.error)));
  });
}

async function kvGet(key) {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const rq = tx.objectStore(STORE).get(key);
      rq.onsuccess = () => resolve(rq.result ?? null);
      rq.onerror = () => reject(rq.error);
    });
  } finally {
    db.close();
  }
}

async function kvPut(key, value) {
  const db = await openDb();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error(String(tx.error)));
    });
  } finally {
    db.close();
  }
}

async function kvDelete(key) {
  const db = await openDb();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error(String(tx.error)));
    });
  } finally {
    db.close();
  }
}

export function isArtifactsScopePickerSupported() {
  return typeof window !== 'undefined' && window.isSecureContext === true
    && typeof window.showDirectoryPicker === 'function'
    && typeof window.showOpenFilePicker === 'function';
}

export async function requestDirectoryReadAccess(handle) {
  if (!handle?.queryPermission) {
    return true;
  }
  const queried = await handle.queryPermission({ mode: 'read' });
  if (queried === 'granted') {
    return true;
  }
  const requested = await handle.requestPermission({ mode: 'read' });
  return requested === 'granted';
}

/**
 * Navigate as deep as matching segment names permit; stops at first missing folder.
 */
async function descendOrStop(root, segments) {
  let dir = root;
  let lastResolved = root;
  for (const seg of segments) {
    try {
      dir = await dir.getDirectoryHandle(seg);
      lastResolved = dir;
    } catch {
      break;
    }
  }
  return lastResolved;
}

export async function loadPersistedArtifactsRoot() {
  return kvGet(ARTIFACT_SCOPE_KEY);
}

export async function persistArtifactsFolderFromUser() {
  const handle = await window.showDirectoryPicker({ id: 'capstone-artifacts-root' });
  if (!(await requestDirectoryReadAccess(handle))) {
    throw new Error('Read permission denied for the selected folder.');
  }
  await kvPut(ARTIFACT_SCOPE_KEY, handle);
  return handle;
}

export async function clearPersistedArtifactsRoot() {
  await kvDelete(ARTIFACT_SCOPE_KEY);
}

async function startInSuggested(rootHandle, chains) {
  if (!rootHandle) {
    return undefined;
  }
  if (!(await requestDirectoryReadAccess(rootHandle))) {
    return undefined;
  }
  for (const chain of chains) {
    const deepest = await descendOrStop(rootHandle, chain);
    if (deepest) {
      return deepest;
    }
  }
  return rootHandle;
}

export async function getLivePipelineStartDirectory() {
  const root = await loadPersistedArtifactsRoot();
  return startInSuggested(root, [['artifacts', 'live'], ['live']]);
}

export async function getBenchPipelineStartDirectory() {
  const root = await loadPersistedArtifactsRoot();
  return startInSuggested(root, [['artifacts', 'bench'], ['bench']]);
}

function isAbortDomError(reason) {
  if (!reason) {
    return false;
  }
  if (reason instanceof DOMException) {
    return reason.code === DOMException.ABORT_ERR || reason.name === 'AbortError';
  }
  if (typeof reason !== 'object') {
    return false;
  }
  return /** @type {{ name?: string }} */ (reason).name === 'AbortError';
}

/** @returns {Promise<File>} */
export async function pickArtifactJsonWithScope() {
  const startIn = await getLivePipelineStartDirectory();
  const [picked] = await window.showOpenFilePicker({
    id: 'capstone-picker-live-runtime-json',
    multiple: false,
    startIn,
    types: [{ description: 'Live runtime JSON', accept: { 'application/json': ['.json'] } }],
  });
  return picked.getFile();
}

/** @returns {Promise<File>} */
export async function pickBenchmarkJsonWithScope() {
  const startIn = await getBenchPipelineStartDirectory();
  const [picked] = await window.showOpenFilePicker({
    id: 'capstone-picker-bench-evidence-json',
    multiple: false,
    startIn,
    types: [{ description: 'Benchmark / evidence JSON', accept: { 'application/json': ['.json'] } }],
  });
  return picked.getFile();
}

/** @returns {Promise<File>} */
export async function pickInputWaveWavWithScope() {
  const startIn = await getLivePipelineStartDirectory();
  const [picked] = await window.showOpenFilePicker({
    id: 'capstone-picker-waveform-input-wav',
    multiple: false,
    startIn,
    types: [{ description: 'Input WAV', accept: { 'audio/wav': ['.wav'] } }],
  });
  return picked.getFile();
}

/** @returns {Promise<File[]>} */
export async function pickStemWaveWavsWithScope() {
  const startIn = await getLivePipelineStartDirectory();
  const list = await window.showOpenFilePicker({
    id: 'capstone-picker-waveform-stem-wavs',
    multiple: true,
    startIn,
    types: [{ description: 'Stem WAV files', accept: { 'audio/wav': ['.wav'] } }],
  });
  const files = await Promise.all(list.map((h) => h.getFile()));
  return files;
}

export function assignFilesToHtmlInput(input, files, { dispatchChange = true } = {}) {
  const dt = new DataTransfer();
  const arr = Array.isArray(files) ? files : [files];
  for (const file of arr) {
    dt.items.add(file);
  }
  /** @type {HTMLInputElement} */ (input).files = dt.files;
  if (dispatchChange) {
    /** @type {HTMLInputElement} */ (input).dispatchEvent(new Event('change', { bubbles: true }));
  }
}

/**
 * Runs the structured picker flow; hides AbortErrors.
 */
export async function runScopedKindPicker(kind, elementsByKind) {
  try {
    if (kind === 'artifact') {
      const file = await pickArtifactJsonWithScope();
      assignFilesToHtmlInput(elementsByKind.artifact, file);
      return;
    }
    if (kind === 'benchmark') {
      const file = await pickBenchmarkJsonWithScope();
      assignFilesToHtmlInput(elementsByKind.benchmark, file);
      return;
    }
    if (kind === 'wav-input') {
      const file = await pickInputWaveWavWithScope();
      assignFilesToHtmlInput(elementsByKind.wavInput, file);
      return;
    }
    if (kind === 'wav-stems') {
      const files = await pickStemWaveWavsWithScope();
      assignFilesToHtmlInput(elementsByKind.wavStems, files);
    }
  } catch (err) {
    if (!isAbortDomError(err)) {
      throw err;
    }
  }
}
