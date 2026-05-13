from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT_SCRIPT = PROJECT_ROOT / "scripts/export/export_umx_onnx.py"


def _bash_path_arg(arg: str) -> str:
    """Non-WSL: forward slashes with stable drive-letter casing."""
    if sys.platform != "win32" or not arg:
        return arg
    if re.match(r"^[A-Za-z]:[/\\]", arg):
        return Path(arg).resolve().as_posix()
    return arg


def _win32_wsl_path(path: Path) -> str:
    """Map Windows paths for WSL shells launched from PowerShell (subprocess env is not forwarded)."""
    if sys.platform != "win32":
        return str(path.resolve())
    s = path.resolve().as_posix()
    m = re.match(r"^([A-Za-z]):/(.*)$", s)
    if not m:
        return s
    drive, tail = m.group(1).lower(), m.group(2)
    return f"/mnt/{drive}/{tail}"


def _wsl_path_arg(arg: str) -> str:
    if sys.platform != "win32" or not arg:
        return arg
    if re.match(r"^[A-Za-z]:[/\\]", arg):
        return _win32_wsl_path(Path(arg))
    return arg


def _bash_env() -> dict[str, str]:
    env = os.environ.copy()
    bindir = str(Path(sys.executable).resolve().parent)
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    env["PYTHON"] = sys.executable
    return env


def _run_export(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(EXPORT_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _run_build(*args: str) -> subprocess.CompletedProcess[str]:
    if sys.platform == "win32":
        converted = [_wsl_path_arg(a) for a in args]
        wsl_root = _win32_wsl_path(PROJECT_ROOT)
        script_args = ["scripts/export/build_trt_engine.sh", *converted]
        cmd_str = (
            f"cd {shlex.quote(wsl_root)} && export PYTHON=python3 && exec bash "
            + " ".join(shlex.quote(a) for a in script_args)
        )
        return subprocess.run(
            ["bash", "-c", cmd_str],
            capture_output=True,
            text=True,
            check=False,
        )
    converted = [_bash_path_arg(a) for a in args]
    cmd = ["bash", "scripts/export/build_trt_engine.sh", *converted]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(PROJECT_ROOT),
        env=_bash_env(),
    )


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


def test_trt_build_dry_run_writes_valid_json_log(tmp_path: Path) -> None:
    onnx_path = tmp_path / "model.onnx"
    engine_path = tmp_path / "model.engine"
    cache_path = tmp_path / "timing.cache"
    log_path = PROJECT_ROOT / "artifacts/bench/trt/pytest-build-log.json"
    onnx_path.write_bytes(b"onnx")
    log_path.parent.mkdir(parents=True, exist_ok=True)

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
        str(cache_path),
        "--log-path",
        str(log_path),
        "--dry-run",
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["error_stage"] is None
    assert payload["error_message"] == "dry_run"
