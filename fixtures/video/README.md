# Video Fixture Policy

`fixtures/video/demo_mix.mp4` is a deterministic container fixture that carries the same synthetic audio bed used by the MP3 smoke path.

## Why this exists

- The live ingest path needs to prove that MP4/MOV container audio reaches the same decoded runtime envelope as file-backed MP3 sources.
- CI must not depend on external downloads or licensed media.
- The fixture should stay tiny, reproducible, and self-contained.
- The source-mode regression tests and unified slice verifier use this fixture to confirm that `--source-mode video-audio` resolves to the shared decoded runtime contract.

## Generation behavior

The fixture is generated from `fixtures/audio/10s_mix.wav` plus a synthetic test-pattern video stream using the bundled ffmpeg binary from `imageio_ffmpeg`.
The file keeps the same 10-second audio duration as the MP3 smoke fixture so the live runtime produces the same chunking behavior when decoded with the default smoke settings.

## Regeneration command

```bash
FFMPEG_BIN="$(python - <<'PY'
from pathlib import Path
import site
user_site = Path(site.getusersitepackages())
binaries = user_site / 'imageio_ffmpeg' / 'binaries'
for candidate in sorted(binaries.iterdir()):
    if candidate.name.startswith('ffmpeg-') and candidate.is_file():
        print(candidate)
        break
PY
)"

"${FFMPEG_BIN}" -y \
  -f lavfi -i "testsrc=duration=10:size=64x64:rate=1" \
  -i fixtures/audio/10s_mix.wav \
  -map 0:v:0 -map 1:a:0 \
  -c:v libx264 -pix_fmt yuv420p -preset veryfast -crf 28 \
  -c:a aac -b:a 128k \
  -shortest \
  fixtures/video/demo_mix.mp4
```

## Constraints

- Do not replace this fixture with proprietary or user-provided source material.
- Keep the file small enough for fast test startup.
- If regeneration is needed, use the same synthetic audio source and keep the container duration aligned with the MP3 smoke fixture.
- If a future verifier needs to debug `video-audio` coverage, start with this fixture and the `scripts/verify/s03_check.sh` output directory noted in the task summary.
