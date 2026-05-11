from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_trt_build_dry_run_writes_valid_json_log(tmp_path: Path) -> None:
    onnx_path = tmp_path / "model.onnx"
    engine_path = tmp_path / "model.engine"
    cache_path = tmp_path / "timing.cache"
    log_path = tmp_path / "build_log.json"
    onnx_path.write_bytes(b"onnx")

    proc = subprocess.run(
        [
            "bash",
            "scripts/export/build_trt_engine.sh",
            "--onnx",
            str(onnx_path),
            "--engine",
            str(engine_path),
            "--min-shape",
            "1x2x22050",
            "--opt-shape",
            "1x2x44100",
            "--max-shape",
            "1x2x88200",
            "--timing-cache",
            str(cache_path),
            "--log-path",
            str(log_path),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["error_stage"] is None
    assert payload["error_message"] == "dry_run"
