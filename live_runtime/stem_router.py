from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING
import wave

import numpy as np

from .contracts import StemRouting
from .source_ingest import SourceIngestEnvelope

if TYPE_CHECKING:
    pass

DEFAULT_VOCALS_NAME = "vocals.wav"
DEFAULT_DRUMS_NAME = "drums.wav"
DEFAULT_BASS_NAME = "bass.wav"
DEFAULT_OTHER_NAME = "other.wav"
DEFAULT_MIX_NAME = "mix.wav"
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StemRoutingError(RuntimeError):
    """Raised when stem output routing cannot be completed safely."""

    error_stage: str
    output_dir: Path
    message: str

    def __str__(self) -> str:
        return self.message


def resolve_live_stem_routing(
    output_dir: Path | str,
    *,
    vocals_name: str = DEFAULT_VOCALS_NAME,
    drums_name: str = DEFAULT_DRUMS_NAME,
    bass_name: str = DEFAULT_BASS_NAME,
    other_name: str = DEFAULT_OTHER_NAME,
) -> StemRouting:
    """Compute the exact four live stem paths under the requested output directory."""

    root = Path(output_dir)
    return StemRouting(
        vocals_path=str(root / vocals_name),
        drums_path=str(root / drums_name),
        bass_path=str(root / bass_name),
        other_path=str(root / other_name),
    )


def _write_wav(path: Path, *, sample_rate_hz: int, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(pcm)


def write_live_mix_wav(
    output_dir: Path | str,
    *,
    sample_rate_hz: int,
    pcm: bytes,
    mix_name: str = DEFAULT_MIX_NAME,
) -> Path:
    """Write mono 16-bit PCM ``mix.wav`` (decoded source) beside stem outputs.

    Consumed by the compare UI Input lane waveform and playback when the artifact
    ``input`` field is not a ``.wav`` path.
    """

    dest = Path(output_dir) / mix_name
    _write_wav(dest, sample_rate_hz=sample_rate_hz, pcm=pcm)
    return dest


def _build_silence_pcm(source_ingest: SourceIngestEnvelope) -> bytes:
    """Produce a deterministic silence bed that matches the decoded frame count."""

    decoded = source_ingest.decoded_audio
    frame_width = decoded.sample_width_bytes * decoded.channels
    if frame_width <= 0:
        raise StemRoutingError(
            error_stage="output_write_failed",
            output_dir=decoded.source_path.parent,
            message="invalid decoded audio metadata for stem routing",
        )

    if len(decoded.pcm) % frame_width != 0:
        raise StemRoutingError(
            error_stage="output_write_failed",
            output_dir=decoded.source_path.parent,
            message="decoded PCM was not frame aligned for stem routing",
        )

    return b"\x00\x00" * (len(decoded.pcm) // decoded.sample_width_bytes)


def write_live_stems(
    source_ingest: SourceIngestEnvelope,
    output_dir: Path | str,
    *,
    vocals_name: str = DEFAULT_VOCALS_NAME,
    drums_name: str = DEFAULT_DRUMS_NAME,
    bass_name: str = DEFAULT_BASS_NAME,
    other_name: str = DEFAULT_OTHER_NAME,
) -> StemRouting:
    """Write exactly four live stem WAVs from a pre-decoded source envelope."""

    output_root = Path(output_dir)
    if output_root.exists() and not output_root.is_dir():
        raise StemRoutingError(
            error_stage="output_write_failed",
            output_dir=output_root,
            message=f"output directory is not writable: {output_root}",
        )

    output_root.mkdir(parents=True, exist_ok=True)
    routing = resolve_live_stem_routing(
        output_root,
        vocals_name=vocals_name,
        drums_name=drums_name,
        bass_name=bass_name,
        other_name=other_name,
    )

    decoded = source_ingest.decoded_audio
    silence_pcm = _build_silence_pcm(source_ingest)

    stem_payloads = {
        "vocals": (Path(routing.vocals_path), decoded.pcm),
        "drums": (Path(routing.drums_path), silence_pcm),
        "bass": (Path(routing.bass_path), silence_pcm),
        "other": (Path(routing.other_path), silence_pcm),
    }

    staging_root = Path(tempfile.mkdtemp(prefix="live-stems-", dir=str(output_root.parent)))
    staged_paths: list[Path] = []
    try:
        for _stem_name, (final_path, pcm) in stem_payloads.items():
            staged_path = staging_root / final_path.name
            _write_wav(staged_path, sample_rate_hz=decoded.sample_rate_hz, pcm=pcm)
            staged_paths.append(staged_path)

        for _stem_name, (final_path, _) in stem_payloads.items():
            _log.debug("writing live stem %s to %s", _stem_name, final_path)
            (staging_root / final_path.name).replace(final_path)
    except FileNotFoundError as exc:
        _log.error("stem output directory write failed for %s: %s", output_root, exc)
        raise StemRoutingError(
            error_stage="output_write_failed",
            output_dir=output_root,
            message=f"output directory write failed for {output_root}: {exc}",
        ) from exc
    except OSError as exc:
        _log.error("stem output directory write failed for %s: %s", output_root, exc)
        raise StemRoutingError(
            error_stage="output_write_failed",
            output_dir=output_root,
            message=f"output directory write failed for {output_root}: {exc}",
        ) from exc
    finally:
        for staged_file in staged_paths:
            try:
                staged_file.unlink()
            except FileNotFoundError:
                pass
        try:
            staging_root.rmdir()
        except OSError:
            pass

    return routing


def write_live_stems_from_arrays(
    stem_arrays: dict[str, np.ndarray],
    output_dir: Path | str,
    sample_rate_hz: int,
    *,
    vocals_name: str = DEFAULT_VOCALS_NAME,
    drums_name: str = DEFAULT_DRUMS_NAME,
    bass_name: str = DEFAULT_BASS_NAME,
    other_name: str = DEFAULT_OTHER_NAME,
) -> StemRouting:
    """Write four stem WAVs from real separated numpy arrays (channels, samples)."""
    from .umx_separator import stem_to_mono_pcm

    output_root = Path(output_dir)
    if output_root.exists() and not output_root.is_dir():
        raise StemRoutingError(
            error_stage="output_write_failed",
            output_dir=output_root,
            message=f"output directory is not writable: {output_root}",
        )

    output_root.mkdir(parents=True, exist_ok=True)
    routing = resolve_live_stem_routing(
        output_root,
        vocals_name=vocals_name,
        drums_name=drums_name,
        bass_name=bass_name,
        other_name=other_name,
    )

    name_to_path = {
        "vocals": Path(routing.vocals_path),
        "drums": Path(routing.drums_path),
        "bass": Path(routing.bass_path),
        "other": Path(routing.other_path),
    }
    name_to_wav_name = {
        "vocals": vocals_name,
        "drums": drums_name,
        "bass": bass_name,
        "other": other_name,
    }

    staging_root = Path(tempfile.mkdtemp(prefix="live-stems-", dir=str(output_root.parent)))
    staged_paths: list[Path] = []
    try:
        for stem_name, final_path in name_to_path.items():
            arr = stem_arrays.get(stem_name)
            pcm = stem_to_mono_pcm(arr) if arr is not None else b"\x00\x00" * 1024
            staged_path = staging_root / name_to_wav_name[stem_name]
            _write_wav(staged_path, sample_rate_hz=sample_rate_hz, pcm=pcm)
            staged_paths.append(staged_path)

        for stem_name, final_path in name_to_path.items():
            _log.debug("writing live stem %s to %s", stem_name, final_path)
            (staging_root / name_to_wav_name[stem_name]).replace(final_path)
    except OSError as exc:
        _log.error("stem write failed for %s: %s", output_root, exc)
        raise StemRoutingError(
            error_stage="output_write_failed",
            output_dir=output_root,
            message=f"stem write failed: {exc}",
        ) from exc
    finally:
        for staged_file in staged_paths:
            try:
                staged_file.unlink()
            except FileNotFoundError:
                pass
        try:
            staging_root.rmdir()
        except OSError:
            pass

    return routing
