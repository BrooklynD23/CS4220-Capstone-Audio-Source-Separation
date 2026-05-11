# Operations Runbook

## Prerequisites

- Python `>=3.10,<3.13`
- CUDA and NVIDIA driver compatible with the installed TensorRT tools
- TensorRT `trtexec` available on `PATH` for engine builds
- `ffmpeg` available on `PATH` or via `imageio-ffmpeg`

## First-Time Setup

```bash
python -m pip install -e ".[gpu,mic]"
```

Place model weights at:

- `artifacts/models/umx-live.pt`
- `artifacts/models/demucs-live.pt` if exercising the Demucs request path

## Running Live Separation

MP3 source:

```bash
python scripts/live/run_live_separation.py \
  --source-mode mp3 \
  --input fixtures/audio/demo_mix.mp3 \
  --output-dir artifacts/live/smoke
```

Microphone source:

```bash
python scripts/live/run_live_separation.py \
  --source-mode mic \
  --mic-device default \
  --mic-backend sounddevice \
  --output-dir artifacts/live/mic
```

Video source:

```bash
python scripts/live/run_live_separation.py \
  --source-mode video-audio \
  --input fixtures/video/demo_mix.mp4 \
  --output-dir artifacts/live/video
```

## Running The Compare UI

```bash
python scripts/ui/serve_compare_demo.py
```

Open `http://localhost:8000` and check side-by-side, overlay, and timeline modes.

## Expected Performance

- Throughput: about `0.6` chunks/sec, with an operational floor of `0.5` chunks/sec
- Mic latency: about `1575ms` end to end, with an operational ceiling of `2000ms`
- Eval threshold: vocal SDR median `>=5.0 dB`
- Live runtime health: `healthy`; investigate `degraded` or `fallback`

## Common Failures And Fixes

- `ffmpeg` not found: install `ffmpeg` and add it to `PATH`.
- Model not found at `artifacts/models/umx-live.pt`: download or place model weights at that path.
- Inference hangs: kill the process, then check GPU memory with `nvidia-smi`.
- Partial artifact output: re-run the command. `stem_router` uses atomic writes, so partial artifact directories are safe to delete.

## GPU/CUDA Notes

The locked environment assumptions live in [configs/environment.lock.md](../../configs/environment.lock.md).
