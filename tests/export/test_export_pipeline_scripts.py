from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT_SCRIPT = PROJECT_ROOT / "scripts/export/export_umx_onnx.py"
BUILD_SCRIPT = PROJECT_ROOT / "scripts/export/build_trt_engine.sh"


def _run_export(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(EXPORT_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _run_build(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", str(BUILD_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def test_export_dry_run_writes_onnx_and_metadata(tmp_path: Path) -> None:
    onnx_path = tmp_path / "model.onnx"
    metadata_path = tmp_path / "export_meta.json"

    proc = _run_export(
        "--onnx-output",
        str(onnx_path),
        "--metadata-output",
        str(metadata_path),
        "--model-source",
        "umx.pretrained:umxhq",
        "--input-shape",
        "1,2,44100",
        "--min-shape",
        "1,2,22050",
        "--opt-shape",
        "1,2,44100",
        "--max-shape",
        "1,2,88200",
        "--dry-run",
    )

    assert proc.returncode == 0, proc.stderr
    assert onnx_path.exists()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert metadata["status"] == "ok"
    assert metadata["opset"] >= 13
    assert metadata["input_shape"] == [1, 2, 44100]
    assert metadata["profile"]["min"] == [1, 2, 22050]
    assert metadata["profile"]["opt"] == [1, 2, 44100]
    assert metadata["profile"]["max"] == [1, 2, 88200]
    assert metadata["model_source"] == "umx.pretrained:umxhq"
    assert metadata["onnx_output"] == str(onnx_path)


def test_export_rejects_invalid_output_path(tmp_path: Path) -> None:
    bad_path = tmp_path / "output_dir"
    bad_path.mkdir(parents=True)

    proc = _run_export(
        "--onnx-output",
        str(bad_path),
        "--input-shape",
        "1,2,44100",
        "--min-shape",
        "1,2,22050",
        "--opt-shape",
        "1,2,44100",
        "--max-shape",
        "1,2,88200",
        "--dry-run",
    )

    assert proc.returncode != 0
    assert "invalid_onnx_output_path" in proc.stderr


def test_export_rejects_malformed_profiles(tmp_path: Path) -> None:
    onnx_path = tmp_path / "model.onnx"
    proc = _run_export(
        "--onnx-output",
        str(onnx_path),
        "--input-shape",
        "1,2,44100",
        "--min-shape",
        "1,2,50000",
        "--opt-shape",
        "1,2,44100",
        "--max-shape",
        "1,2,88200",
        "--dry-run",
    )

    assert proc.returncode != 0
    assert "invalid_profile" in proc.stderr


def test_build_rejects_empty_timing_cache_path(tmp_path: Path) -> None:
    onnx_path = tmp_path / "model.onnx"
    onnx_path.write_text("onnx", encoding="utf-8")
    engine_path = tmp_path / "model.engine"

    proc = _run_build(
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
        "",
        "--dry-run",
    )

    assert proc.returncode != 0
    assert "timing-cache path must not be empty" in proc.stderr.lower()


def test_build_rejects_malformed_profile(tmp_path: Path) -> None:
    onnx_path = tmp_path / "model.onnx"
    onnx_path.write_text("onnx", encoding="utf-8")
    engine_path = tmp_path / "model.engine"

    proc = _run_build(
        "--onnx",
        str(onnx_path),
        "--engine",
        str(engine_path),
        "--min-shape",
        "1,2,22050",
        "--opt-shape",
        "1x2x44100",
        "--max-shape",
        "1x2x88200",
        "--dry-run",
    )

    assert proc.returncode != 0
    assert "malformed profile" in proc.stderr.lower()


def test_build_missing_trtexec_returns_guidance(tmp_path: Path) -> None:
    onnx_path = tmp_path / "model.onnx"
    onnx_path.write_text("onnx", encoding="utf-8")
    engine_path = tmp_path / "model.engine"

    proc = _run_build(
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
        "--trtexec",
        str(tmp_path / "missing-trtexec"),
    )

    assert proc.returncode != 0
    assert "trtexec not found" in proc.stderr.lower()


def test_build_dry_run_prints_exact_command_and_is_idempotent(tmp_path: Path) -> None:
    onnx_path = tmp_path / "model.onnx"
    onnx_path.write_text("onnx", encoding="utf-8")
    engine_path = tmp_path / "model.engine"
    timing_cache = tmp_path / "timing.cache"

    first = _run_build(
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
        str(timing_cache),
        "--dry-run",
    )
    second = _run_build(
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
        str(timing_cache),
        "--dry-run",
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "trtexec command:" in first.stdout.lower()
    assert engine_path.exists()
