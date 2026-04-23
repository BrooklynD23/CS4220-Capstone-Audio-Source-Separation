# Audio Fixture Policy

`fixtures/audio/10s_mix.wav` is a synthetic, non-proprietary placeholder clip used for deterministic benchmark smoke tests.
`fixtures/audio/demo_mix.mp3` is a checked-in MP3 smoke fixture generated from that WAV placeholder with the bundled ffmpeg binary so live ingest tests can exercise actual MP3 decode/resample paths.

## Why this exists

- CI must run timing harnesses without requiring MUSDB18 or licensed stems.
- Benchmark scripts need a stable input shape for contract validation.
- Live ingest tests need a deterministic MP3 source that can be decoded without external downloads.
- The mic source-mode coverage uses a fake backend and this MP3 fixture as the synthetic audio baseline for regression comparisons.

## Generation behavior

`scripts/benchmark/run_stage_timing.py` auto-generates `fixtures/audio/10s_mix.wav` on first run if the file is missing.
The generated fixture is a 10-second mono sine tone at 44.1 kHz.
`fixtures/audio/demo_mix.mp3` is derived from `10s_mix.wav` with the bundled ffmpeg binary and kept in the repository so tests do not depend on a local encoder.

## Constraints

- Do not replace this fixture with proprietary or user-provided source material.
- Keep this fixture small and deterministic for repeatable smoke runs.
- If the MP3 fixture needs regeneration, use the same source WAV and a deterministic encoder preset so the ingest tests remain stable.
- When extending source-mode coverage, prefer deterministic fakes such as `FakeMicCaptureBackend` over live hardware so CI stays reproducible.
