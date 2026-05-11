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
    _tmp_path: Path | None = None
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
        _tmp_path = Path(tmp.name)
        input_path = _tmp_path

    try:
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

        try:
            stream_v.start_stream()
            stream_i.start_stream()
            print("Playing back — close the window to stop.")
            plt.show()
        finally:
            for s in (stream_v, stream_i):
                s.stop_stream()
                s.close()
            pa.terminate()
            if nvml is not None:
                try:
                    nvml.nvmlShutdown()
                except Exception:
                    pass
    finally:
        if _tmp_path is not None:
            _tmp_path.unlink(missing_ok=True)


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
