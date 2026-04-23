# Scripts Reference

All CLI entry points under `scripts/`. Each script is runnable as `python scripts/<group>/<name>.py`.

## Script Overview

| Script | Group | Purpose |
|---|---|---|
| [`assemble_capstone_evidence.py`](benchmark.md#assemble_capstone_evidencepy) | benchmark | Assemble the final S06 capstone evidence manifest from all phase artifacts |
| [`run_live_throughput.py`](benchmark.md#run_live_throughputpy) | benchmark | Measure live separation throughput (wall-clock ms per 1-second chunk) |
| [`run_mic_latency.py`](benchmark.md#run_mic_latencypy) | benchmark | Measure end-to-end microphone capture latency through the live separation path |
| [`run_stage_timing.py`](benchmark.md#run_stage_timingpy) | benchmark | Run per-stage (STFT / infer / ISTFT) timing benchmark on a WAV fixture |
| [`aggregate_metrics.py`](eval.md#aggregate_metricspy) | eval | Aggregate per-track vocals SDR values into a summary verdict |
| [`run_umx_eval.py`](eval.md#run_umx_evalpy) | eval | Run UMX evaluation and emit per-track metrics artifacts |
| [`export_umx_onnx.py`](export.md#export_umx_onnxpy) | export | Export the UMX model to ONNX with deterministic metadata |
| [`run_live_separation.py`](live.md#run_live_separationpy) | live | Run live smoke separation and emit a JSON artifact plus four WAV stems |
| [`serve_compare_demo.py`](ui.md#serve_compare_demopy) | ui | Serve the static compare UI over HTTP |
| [`validate_json.py`](verify.md#validate_jsonpy) | verify | Validate a JSON payload against a JSON Schema (Draft 2020-12) |

## Artifact Hierarchy

```
artifacts/
  eval/           ← run_umx_eval.py, aggregate_metrics.py
  bench/
    live-throughput/   ← run_live_throughput.py
    mic-latency/       ← run_mic_latency.py
    s06-capstone-*/    ← assemble_capstone_evidence.py
    capstone_evidence_manifest.json
  export/         ← export_umx_onnx.py
  live/           ← run_live_separation.py
```

## Detailed Documentation

- [benchmark.md](benchmark.md) — throughput, mic-latency, stage-timing, capstone evidence
- [eval.md](eval.md) — UMX evaluation runner and metric aggregation
- [export.md](export.md) — ONNX export
- [live.md](live.md) — live separation CLI
- [ui.md](ui.md) — compare UI HTTP server
- [verify.md](verify.md) — JSON schema validation
