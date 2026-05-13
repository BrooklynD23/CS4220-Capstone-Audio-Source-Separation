# umx_separator

**File:** `live_runtime/umx_separator.py`

Optional **Open-Unmix `umxhq`** separation helpers used when **`--mode full`** is requested from [`scripts/live/run_live_separation.py`](../scripts/live.md).

This module imports **Torch** / **Open-Unmix lazily**. Coverage omits this file unless you opt into GPU/full runs locally.

---

## Overview

| Function / type | Purpose |
|---|---|
| `is_available()` | `True` iff `torch` and `openunmix` import cleanly |
| `resolve_device(requested)` | Maps `"gpu"`/`"cuda"` → `"cuda"` when available, otherwise `"cpu"` |
| `load_umxhq_separator(device)` | Loads `openunmix.umxhq(..., pretrained=True)` — downloads weights on first use |
| `separate_tensor(audio, sample_rate_hz, separator, device)` | Runs forward pass with staged wall timings (`stft_ms`, `infer_ms`, `istft_ms`) |
| `pcm_to_tensor(pcm)`, `stem_to_mono_pcm(array)` | Int16 PCM ↔ stereo float tensors for WAV IO |

Checkpoint path strings such as **`artifacts/models/umx-live.pt`** are **not read** here; **`pretrained=True`** pulls the bundled `umxhq` checkpoint from Open-Unmix tooling. Align documentation with **`scripts/models/bootstrap_umx_live_checkpoint.py`** when discussing on-disk `.pt` files.

---

## Constants

| Name | Meaning |
|---|---|
| `SEPARATOR_SAMPLE_RATE` | Expected Open-Unmix internal rate (`44100`) |
| `STEM_NAMES` | `("vocals", "drums", "bass", "other")` |

Timing buckets mirror the live-runtime contract: preprocessing+STFT, Wiener-mask inference, inverse STFT.

---

## Typical call graph

CLI full mode resolves device → imports module → builds tensor from decoded PCM → `separate_tensor` → `stem_router.write_live_stems_from_arrays` → schema-valid artifact.
