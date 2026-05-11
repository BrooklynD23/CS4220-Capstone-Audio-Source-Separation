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


def separate_tensor(
    audio: "torch.Tensor",
    sample_rate_hz: int,
    separator: Any,
    device: str = "cuda",
) -> SeparationResult:
    """Run umxhq on a (channels, samples) float32 tensor.

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

    audio_device = audio.to(device)
    audio_prep = utils.preprocess(audio_device, sample_rate_hz, separator.sample_rate)

    t0 = time.perf_counter()
    with torch.no_grad():
        estimates_raw = separator(audio_prep)
    infer_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    estimates = separator.to_dict(estimates_raw)
    stems: dict[str, np.ndarray] = {}
    for target, tensor in estimates.items():
        # shape: (batch, channels, samples) → squeeze batch → (channels, samples)
        stems[target] = tensor.squeeze(0).cpu().numpy()

    return SeparationResult(
        stems=stems,
        sample_rate_hz=separator.sample_rate,
        timings=SeparationTimings(
            stft_ms=0.0,
            infer_ms=infer_ms,
            istft_ms=0.0,
            total_ms=infer_ms,
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
