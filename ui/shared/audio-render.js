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
