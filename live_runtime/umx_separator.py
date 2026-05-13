"""Real UMX/umxhq separation using open-unmix.

Provides GPU-accelerated source separation via the pretrained umxhq model.
Falls back gracefully when torch or openunmix are not installed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import torch

SEPARATOR_SAMPLE_RATE = 44100
STEM_NAMES = ("vocals", "drums", "bass", "other")


@dataclass(frozen=True)
class SeparationTimings:
    stft_ms: float
    infer_ms: float
    istft_ms: float
    total_ms: float


@dataclass(frozen=True)
class SeparationResult:
    stems: dict[str, np.ndarray]  # target -> (channels, samples) float32
    sample_rate_hz: int
    timings: SeparationTimings


def is_available() -> bool:
    """Return True if torch and openunmix are importable."""
    try:
        import torch  # noqa: F401
        import openunmix  # noqa: F401
        return True
    except ImportError:
        return False


def resolve_device(requested: str) -> str:
    """Return the best available device, falling back to cpu."""
    try:
        import torch
        if requested == "gpu" or requested == "cuda":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return requested
    except ImportError:
        return "cpu"


def load_umxhq_separator(device: str = "cuda") -> Any:
    """Download (on first call) and load the umxhq separator onto device."""
    import openunmix
    separator = openunmix.umxhq(
        targets=list(STEM_NAMES),
        device=device,
        pretrained=True,
    )
    separator.freeze()
    return separator


def _int_sample_rate_hz(sample_rate: Any) -> int:
    """Open-Unmix may expose ``sample_rate`` as a scalar torch.Tensor; wave needs a Python int."""
    if hasattr(sample_rate, "item"):
        return int(sample_rate.item())
    return int(sample_rate)


def _sync_device_timers(device: str) -> None:
    """Await queued GPU work so perf timers reflect completed kernels."""
    if device == "cuda":
        import torch

        torch.cuda.synchronize()


def separate_tensor(
    audio: "torch.Tensor",
    sample_rate_hz: int,
    separator: Any,
    device: str = "cuda",
) -> SeparationResult:
    """Run umxhq on a (channels, samples) float32 tensor.

    Mirrors ``openunmix.model.Separator.forward`` with per-stage wall times:
    ``stft_ms`` (resample + STFT + complex norm), ``infer_ms`` (target nets + Wiener),
    ``istft_ms`` (inverse STFT).

    Args:
        audio: shape (channels, samples) float32
        sample_rate_hz: sample rate of the audio tensor
        separator: loaded umxhq Separator (from load_umxhq_separator)
        device: torch device string

    Returns:
        SeparationResult with per-stem numpy arrays (channels, samples)
    """
    import torch
    import openunmix.utils as utils
    from openunmix.filtering import wiener

    sep_sr = _int_sample_rate_hz(separator.sample_rate)
    audio_device = audio.to(device)

    _sync_device_timers(device)
    t_stft = time.perf_counter()
    with torch.no_grad():
        audio_prep = utils.preprocess(audio_device, sample_rate_hz, sep_sr)
        mix_stft = separator.stft(audio_prep)
        X = separator.complexnorm(mix_stft)
    _sync_device_timers(device)
    stft_ms = round((time.perf_counter() - t_stft) * 1000.0, 3)

    nb_sources = separator.nb_targets
    nb_samples = audio_prep.shape[0]

    _sync_device_timers(device)
    t_infer = time.perf_counter()
    with torch.no_grad():
        spectrograms = torch.zeros(X.shape + (nb_sources,), dtype=audio_prep.dtype, device=X.device)
        for j, (_target_name, target_module) in enumerate(separator.target_models.items()):
            target_spectrogram = target_module(X.detach().clone())
            spectrograms[..., j] = target_spectrogram

        spectrograms = spectrograms.permute(0, 3, 2, 1, 4)
        mix_stft_perm = mix_stft.permute(0, 3, 2, 1, 4)

        if separator.residual:
            nb_sources += 1

        if nb_sources == 1 and separator.niter > 0:
            raise RuntimeError(
                "Cannot use EM if only one target is estimated. "
                "Provide two targets or create an additional one with `--residual`"
            )

        dev = mix_stft_perm.device
        nb_frames = spectrograms.shape[1]
        targets_stft = torch.zeros(
            mix_stft_perm.shape + (nb_sources,),
            dtype=audio_prep.dtype,
            device=mix_stft_perm.device,
        )
        for sample in range(nb_samples):
            pos = 0
            wiener_win_len = separator.wiener_win_len if separator.wiener_win_len else nb_frames
            while pos < nb_frames:
                end = min(nb_frames, pos + wiener_win_len)
                cur_frame = torch.arange(pos, end, device=dev)
                pos = int(cur_frame[-1].item()) + 1

                targets_stft[sample, cur_frame] = wiener(
                    spectrograms[sample, cur_frame],
                    mix_stft_perm[sample, cur_frame],
                    separator.niter,
                    softmask=separator.softmask,
                    residual=separator.residual,
                )

        targets_stft = targets_stft.permute(0, 5, 3, 2, 1, 4).contiguous()

    _sync_device_timers(device)
    infer_ms = round((time.perf_counter() - t_infer) * 1000.0, 3)

    _sync_device_timers(device)
    t_istft = time.perf_counter()
    with torch.no_grad():
        estimates_raw = separator.istft(targets_stft, length=audio_prep.shape[2])
    _sync_device_timers(device)
    istft_ms = round((time.perf_counter() - t_istft) * 1000.0, 3)

    total_ms = round(stft_ms + infer_ms + istft_ms, 3)

    estimates = separator.to_dict(estimates_raw)
    stems: dict[str, np.ndarray] = {}
    for target, tensor in estimates.items():
        stems[target] = tensor.squeeze(0).cpu().numpy()

    return SeparationResult(
        stems=stems,
        sample_rate_hz=sep_sr,
        timings=SeparationTimings(
            stft_ms=stft_ms,
            infer_ms=infer_ms,
            istft_ms=istft_ms,
            total_ms=total_ms,
        ),
    )


def pcm_to_tensor(pcm: bytes) -> "torch.Tensor":
    """Convert raw mono int16 PCM bytes to a (2, samples) float32 stereo tensor.

    umxhq expects stereo input; we duplicate mono to both channels.
    """
    import torch
    audio_np = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    mono = torch.from_numpy(audio_np.copy()).unsqueeze(0)  # (1, samples)
    return mono.expand(2, -1).contiguous()  # (2, samples)


def stem_to_mono_pcm(stem_array: np.ndarray) -> bytes:
    """Convert a (channels, samples) or (samples,) float32 array to mono int16 PCM."""
    if stem_array.ndim == 2:
        mono = stem_array.mean(axis=0)
    else:
        mono = stem_array
    clipped = np.clip(mono, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()
