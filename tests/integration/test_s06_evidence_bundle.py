from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts/benchmark/assemble_capstone_evidence.py"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_assembler(*args: str, cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT_PATH), *args]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_eval_summary(*, status: str = "ok") -> dict:
    return {
        "protocol_version": "1.0",
        "dataset": "musdb18",
        "track_count": 1,
        "vocal_sdr_median_db": 5.25,
        "threshold_db": 5.0,
        "pass": True,
        "passes_threshold": True,
        "status": status,
        "error_stage": None if status == "ok" else "aggregate_metrics",
        "generated_at": "2026-04-20T00:00:00+00:00",
    }


def _make_throughput_result(*, status: str = "ok", phase: str = "complete") -> dict:
    return {
        "input": "fixtures/audio/demo_mix.mp3",
        "output_dir": "artifacts/bench/live-throughput",
        "live_artifact_path": "artifacts/bench/live-throughput/live_runtime_result.json",
        "chunk_duration_s": 1.0,
        "wall_clock_ms": 2250.0,
        "wall_clock_ms_per_chunk": 2250.0,
        "throughput_chunks_per_second": 0.444444,
        "device_requested": "cpu",
        "device_used": "cpu",
        "source_mode": "mp3",
        "status": status,
        "phase": phase,
        "error_stage": None if status == "ok" else phase,
        "error_message": None if status == "ok" else "wall-clock throughput budget exceeded: 2250.000ms > 2000.000ms",
        "stderr": "",
        "live_cli_exit_code": 0,
        "live_runtime_status": "ok",
        "live_runtime_error_stage": None,
        "live_runtime_error_message": None,
        "timestamp": "2026-04-20T00:00:00+00:00",
        "metadata": {
            "clock_source": "perf_counter",
            "live_timeout_s": 120.0,
            "max_wall_clock_ms": 2500.0,
            "live_command": ["python", "scripts/live/run_live_separation.py"],
            "device_requested": "cpu",
            "device_used": "cpu",
            "source_mode": "mp3",
        },
    }


def _make_mic_latency_result(*, status: str = "ok", phase: str = "complete") -> dict:
    return {
        "input": "fixture:mic-demo",
        "output_dir": "artifacts/bench/mic-latency",
        "live_artifact_path": "artifacts/bench/mic-latency/live_runtime_result.json",
        "capture_backend_name": "fake",
        "capture_duration_s": 1.0,
        "capture_latency_ms": 321.654,
        "end_to_end_latency_ms": 1250.0,
        "device_requested": "cpu",
        "device_used": "cpu",
        "status": status,
        "phase": phase,
        "error_stage": None if status == "ok" else phase,
        "error_message": None if status == "ok" else "mic capture latency exceeded: 321.654ms > 250.000ms",
        "stderr": "",
        "live_cli_exit_code": 0,
        "live_runtime_status": "ok",
        "live_runtime_error_stage": None,
        "live_runtime_error_message": None,
        "timestamp": "2026-04-20T00:00:00+00:00",
        "metadata": {
            "clock_source": "perf_counter",
            "live_timeout_s": 120.0,
            "max_capture_latency_ms": 250.0,
            "live_command": ["python", "scripts/live/run_live_separation.py"],
            "device_requested": "cpu",
            "device_used": "cpu",
            "capture_backend_name": "fake",
            "capture_duration_s": 1.0,
            "source_mode": "mic",
            "model_path": "artifacts/models/umx-live.pt",
        },
    }


def _make_live_runtime_result(*, status: str = "ok") -> dict:
    return {
        "source": {
            "kind": "mp3",
            "reference": "fixtures/audio/demo_mix.mp3",
            "metadata": {
                "origin": "fixture",
            },
        },
        "input": "fixtures/audio/demo_mix.mp3",
        "sample_rate_hz": 22050,
        "chunk_duration_s": 1.0,
        "chunk_index": 0,
        "stft_ms": 123.0,
        "infer_ms": 234.0,
        "istft_ms": 87.0,
        "total_ms": 444.0,
        "status": status,
        "error_stage": None if status == "ok" else "decode_failed",
        "error_message": None if status == "ok" else "fixture runtime failed",
        "timestamp": "2026-04-20T00:00:00+00:00",
        "health_state": "healthy" if status == "ok" else "degraded",
        "health_reason": "runtime operating normally" if status == "ok" else "fixture runtime failed",
        "requested_model_path": "artifacts/models/live.pt",
        "fallback_applied": False,
        "queue_depth": 20,
        "drop_count": 0,
        "model_path": "artifacts/models/live.pt",
        "stem_paths": {
            "vocals": "artifacts/bench/capstone/vocals.wav",
            "drums": "artifacts/bench/capstone/drums.wav",
            "bass": "artifacts/bench/capstone/bass.wav",
            "other": "artifacts/bench/capstone/other.wav",
        },
        "metadata": {
            "device_requested": "cpu",
            "device_used": "cpu",
            "mode": "smoke",
            "clock_source": "ingest",
            "clock_fallback": False,
            "samples_processed": 22050,
            "channels": 1,
            "sample_width_bytes": 2,
            "stages": ["stft", "infer", "istft"],
        },
    }


def _write_compare_logs(server_log: Path, pytest_log: Path) -> None:
    server_log.parent.mkdir(parents=True, exist_ok=True)
    pytest_log.parent.mkdir(parents=True, exist_ok=True)
    server_log.write_text(
        "compare-demo: serving artifacts at http://127.0.0.1:49821/ui/compare/\n"
        "compare-demo: shutdown requested\n"
        "compare-demo: stopped\n",
        encoding="utf-8",
    )
    pytest_log.write_text(
        "============================= test session starts =============================\n"
        "tests/ui/test_compare_ui.py ..\n"
        "============================== 2 passed in 1.25s ==============================\n",
        encoding="utf-8",
    )


@pytest.fixture()
def bundle_dir(tmp_path: Path) -> Path:
    return tmp_path / "bundle"


def test_assembler_builds_manifest_with_ordered_phases_and_provenance(bundle_dir: Path) -> None:
    eval_path = bundle_dir / "eval" / "summary-smoke.json"
    throughput_path = bundle_dir / "bench" / "live-throughput" / "live_throughput_result.json"
    mic_path = bundle_dir / "bench" / "mic-latency" / "mic_latency_result.json"
    live_path = bundle_dir / "live" / "live_runtime_result.json"
    server_log = bundle_dir / "compare" / "server.log"
    pytest_log = bundle_dir / "compare" / "pytest.log"
    manifest_path = bundle_dir / "capstone_evidence_manifest.json"

    _write_json(eval_path, _make_eval_summary())
    _write_json(throughput_path, _make_throughput_result())
    _write_json(mic_path, _make_mic_latency_result())
    _write_json(live_path, _make_live_runtime_result())
    _write_compare_logs(server_log, pytest_log)

    proc = _run_assembler(
        "--output",
        str(manifest_path),
        "--evaluation-summary",
        str(eval_path),
        "--throughput-artifact",
        str(throughput_path),
        "--mic-latency-artifact",
        str(mic_path),
        "--live-runtime-artifact",
        str(live_path),
        "--compare-server-log",
        str(server_log),
        "--compare-pytest-log",
        str(pytest_log),
    )

    assert proc.returncode == 0, proc.stderr
    manifest = _load_json(manifest_path)

    assert manifest["status"] == "ok"
    assert manifest["phase"] == "complete"
    assert manifest["error_stage"] is None
    assert manifest["phase_order"] == ["evaluation", "throughput", "mic_latency", "live_runtime", "compare_ui"]
    assert [phase["name"] for phase in manifest["phases"]] == manifest["phase_order"]
    assert manifest["inputs"] == {
        "evaluation_summary_path": str(eval_path),
        "throughput_artifact_path": str(throughput_path),
        "mic_latency_artifact_path": str(mic_path),
        "live_runtime_artifact_path": str(live_path),
        "compare_server_log_path": str(server_log),
        "compare_pytest_log_path": str(pytest_log),
    }
    assert manifest["phases"][0]["summary"]["pass"] is True
    assert manifest["phases"][1]["summary"]["throughput_chunks_per_second"] == pytest.approx(0.444444)
    assert manifest["phases"][2]["summary"]["capture_latency_ms"] == pytest.approx(321.654)
    assert manifest["phases"][3]["summary"]["health_state"] == "healthy"
    assert manifest["phases"][4]["server_started"] is True
    assert manifest["phases"][4]["pytest_passed"] is True
    assert "compare-demo: serving" in manifest["phases"][4]["server_excerpt"]
    assert "2 passed" in manifest["phases"][4]["pytest_excerpt"]


def test_assembler_preserves_embedded_failure_states_without_hiding_them(bundle_dir: Path) -> None:
    eval_path = bundle_dir / "eval" / "summary-smoke.json"
    throughput_path = bundle_dir / "bench" / "live-throughput" / "live_throughput_result.json"
    mic_path = bundle_dir / "bench" / "mic-latency" / "mic_latency_result.json"
    live_path = bundle_dir / "live" / "live_runtime_result.json"
    server_log = bundle_dir / "compare" / "server.log"
    pytest_log = bundle_dir / "compare" / "pytest.log"
    manifest_path = bundle_dir / "capstone_evidence_manifest.json"

    _write_json(eval_path, _make_eval_summary())
    _write_json(throughput_path, _make_throughput_result(status="error", phase="throughput_budget_exceeded"))
    _write_json(mic_path, _make_mic_latency_result())
    _write_json(live_path, _make_live_runtime_result())
    _write_compare_logs(server_log, pytest_log)

    proc = _run_assembler(
        "--output",
        str(manifest_path),
        "--evaluation-summary",
        str(eval_path),
        "--throughput-artifact",
        str(throughput_path),
        "--mic-latency-artifact",
        str(mic_path),
        "--live-runtime-artifact",
        str(live_path),
        "--compare-server-log",
        str(server_log),
        "--compare-pytest-log",
        str(pytest_log),
    )

    assert proc.returncode == 1
    manifest = _load_json(manifest_path)

    assert manifest["status"] == "error"
    assert manifest["phase"] == "throughput"
    assert manifest["error_stage"] == "throughput_budget_exceeded"
    assert manifest["phases"][1]["status"] == "error"
    assert manifest["phases"][1]["summary"]["phase"] == "throughput_budget_exceeded"
    assert manifest["phases"][4]["status"] == "ok"


def test_assembler_fails_visibly_when_throughput_input_is_missing(bundle_dir: Path) -> None:
    eval_path = bundle_dir / "eval" / "summary-smoke.json"
    mic_path = bundle_dir / "bench" / "mic-latency" / "mic_latency_result.json"
    live_path = bundle_dir / "live" / "live_runtime_result.json"
    server_log = bundle_dir / "compare" / "server.log"
    pytest_log = bundle_dir / "compare" / "pytest.log"
    manifest_path = bundle_dir / "capstone_evidence_manifest.json"

    _write_json(eval_path, _make_eval_summary())
    _write_json(mic_path, _make_mic_latency_result())
    _write_json(live_path, _make_live_runtime_result())
    _write_compare_logs(server_log, pytest_log)

    proc = _run_assembler(
        "--output",
        str(manifest_path),
        "--evaluation-summary",
        str(eval_path),
        "--throughput-artifact",
        str(bundle_dir / "bench" / "live-throughput" / "missing.json"),
        "--mic-latency-artifact",
        str(mic_path),
        "--live-runtime-artifact",
        str(live_path),
        "--compare-server-log",
        str(server_log),
        "--compare-pytest-log",
        str(pytest_log),
    )

    assert proc.returncode == 1
    manifest = _load_json(manifest_path)
    assert manifest["status"] == "error"
    assert manifest["phase"] == "throughput"
    assert manifest["error_stage"] == "throughput_missing"
    assert "missing.json" in manifest["error_message"]
    assert manifest["phases"][-1]["name"] == "throughput"
    assert manifest["phases"][-1]["error_stage"] == "throughput_missing"


def test_assembler_fails_visibly_when_eval_summary_is_malformed(bundle_dir: Path) -> None:
    eval_path = bundle_dir / "eval" / "summary-smoke.json"
    throughput_path = bundle_dir / "bench" / "live-throughput" / "live_throughput_result.json"
    mic_path = bundle_dir / "bench" / "mic-latency" / "mic_latency_result.json"
    live_path = bundle_dir / "live" / "live_runtime_result.json"
    server_log = bundle_dir / "compare" / "server.log"
    pytest_log = bundle_dir / "compare" / "pytest.log"
    manifest_path = bundle_dir / "capstone_evidence_manifest.json"

    eval_path.parent.mkdir(parents=True, exist_ok=True)
    eval_path.write_text("{not-json", encoding="utf-8")
    _write_json(throughput_path, _make_throughput_result())
    _write_json(mic_path, _make_mic_latency_result())
    _write_json(live_path, _make_live_runtime_result())
    _write_compare_logs(server_log, pytest_log)

    proc = _run_assembler(
        "--output",
        str(manifest_path),
        "--evaluation-summary",
        str(eval_path),
        "--throughput-artifact",
        str(throughput_path),
        "--mic-latency-artifact",
        str(mic_path),
        "--live-runtime-artifact",
        str(live_path),
        "--compare-server-log",
        str(server_log),
        "--compare-pytest-log",
        str(pytest_log),
    )

    assert proc.returncode == 1
    manifest = _load_json(manifest_path)
    assert manifest["status"] == "error"
    assert manifest["phase"] == "evaluation"
    assert manifest["error_stage"] == "evaluation_malformed"
    assert "not valid JSON" in manifest["error_message"]
    assert manifest["phases"][0]["name"] == "evaluation"
    assert manifest["phases"][0]["error_stage"] == "evaluation_malformed"


def test_assembler_fails_visibly_when_live_runtime_artifact_is_malformed(bundle_dir: Path) -> None:
    eval_path = bundle_dir / "eval" / "summary-smoke.json"
    throughput_path = bundle_dir / "bench" / "live-throughput" / "live_throughput_result.json"
    mic_path = bundle_dir / "bench" / "mic-latency" / "mic_latency_result.json"
    live_path = bundle_dir / "live" / "live_runtime_result.json"
    server_log = bundle_dir / "compare" / "server.log"
    pytest_log = bundle_dir / "compare" / "pytest.log"
    manifest_path = bundle_dir / "capstone_evidence_manifest.json"

    _write_json(eval_path, _make_eval_summary())
    _write_json(throughput_path, _make_throughput_result())
    _write_json(mic_path, _make_mic_latency_result())
    live_path.parent.mkdir(parents=True, exist_ok=True)
    live_path.write_text('{not-json', encoding='utf-8')
    _write_compare_logs(server_log, pytest_log)

    proc = _run_assembler(
        "--output",
        str(manifest_path),
        "--evaluation-summary",
        str(eval_path),
        "--throughput-artifact",
        str(throughput_path),
        "--mic-latency-artifact",
        str(mic_path),
        "--live-runtime-artifact",
        str(live_path),
        "--compare-server-log",
        str(server_log),
        "--compare-pytest-log",
        str(pytest_log),
    )

    assert proc.returncode == 1
    manifest = _load_json(manifest_path)
    assert manifest["status"] == "error"
    assert manifest["phase"] == "live_runtime"
    assert manifest["error_stage"] == "live_runtime_malformed"
    assert "not valid JSON" in manifest["error_message"]
    assert manifest["phases"][-1]["name"] == "live_runtime"
    assert manifest["phases"][-1]["error_stage"] == "live_runtime_malformed"


@pytest.mark.parametrize(
    ("missing_log", "expected_error_stage"),
    [("server", "compare_ui_server_missing"), ("pytest", "compare_ui_pytest_missing")],
)
def test_assembler_fails_visibly_when_compare_proof_log_is_missing(
    bundle_dir: Path,
    missing_log: str,
    expected_error_stage: str,
) -> None:
    eval_path = bundle_dir / "eval" / "summary-smoke.json"
    throughput_path = bundle_dir / "bench" / "live-throughput" / "live_throughput_result.json"
    mic_path = bundle_dir / "bench" / "mic-latency" / "mic_latency_result.json"
    live_path = bundle_dir / "live" / "live_runtime_result.json"
    server_log = bundle_dir / "compare" / "server.log"
    pytest_log = bundle_dir / "compare" / "pytest.log"
    manifest_path = bundle_dir / "capstone_evidence_manifest.json"

    _write_json(eval_path, _make_eval_summary())
    _write_json(throughput_path, _make_throughput_result())
    _write_json(mic_path, _make_mic_latency_result())
    _write_json(live_path, _make_live_runtime_result())

    if missing_log == "pytest":
        server_log.parent.mkdir(parents=True, exist_ok=True)
        server_log.write_text(
            "compare-demo: serving artifacts at http://127.0.0.1:49821/ui/compare/\n"
            "compare-demo: shutdown requested\n"
            "compare-demo: stopped\n",
            encoding="utf-8",
        )
    else:
        pytest_log.parent.mkdir(parents=True, exist_ok=True)
        pytest_log.write_text(
            "============================= test session starts =============================\n"
            "tests/ui/test_compare_ui.py ..\n"
            "============================== 2 passed in 1.25s ==============================\n",
            encoding="utf-8",
        )

    proc = _run_assembler(
        "--output",
        str(manifest_path),
        "--evaluation-summary",
        str(eval_path),
        "--throughput-artifact",
        str(throughput_path),
        "--mic-latency-artifact",
        str(mic_path),
        "--live-runtime-artifact",
        str(live_path),
        "--compare-server-log",
        str(server_log),
        "--compare-pytest-log",
        str(pytest_log),
    )

    assert proc.returncode == 1
    manifest = _load_json(manifest_path)
    expected_phase = "compare_ui_server" if missing_log == "server" else "compare_ui_pytest"
    assert manifest["status"] == "error"
    assert manifest["phase"] == expected_phase
    assert manifest["error_stage"] == expected_error_stage
    assert "proof output not found" in manifest["error_message"]
    assert str(server_log if missing_log == "server" else pytest_log) in manifest["error_message"]
    assert manifest["phases"][-1]["name"] == expected_phase
    assert manifest["phases"][-1]["error_stage"] == expected_error_stage


@pytest.mark.parametrize(
    ("server_log_text", "pytest_log_text", "expected_error_stage"),
    [
        (
            "compare-demo: started without expected compare output\n",
            "============================= test session starts =============================\n"
            "tests/ui/test_compare_ui.py ..\n"
            "============================== 2 passed in 1.25s ==============================\n",
            "compare_ui_failed",
        ),
        (
            "compare-demo: serving artifacts at http://127.0.0.1:49821/ui/compare/\n"
            "compare-demo: shutdown requested\n"
            "compare-demo: stopped\n",
            "============================= test session starts =============================\n"
            "tests/ui/test_compare_ui.py ..\n"
            "============================== 0 passed in 1.25s ==============================\n",
            "compare_ui_failed",
        ),
    ],
)
def test_assembler_fails_visibly_when_compare_proof_logs_are_missing_markers(
    bundle_dir: Path,
    server_log_text: str,
    pytest_log_text: str,
    expected_error_stage: str,
) -> None:
    eval_path = bundle_dir / "eval" / "summary-smoke.json"
    throughput_path = bundle_dir / "bench" / "live-throughput" / "live_throughput_result.json"
    mic_path = bundle_dir / "bench" / "mic-latency" / "mic_latency_result.json"
    live_path = bundle_dir / "live" / "live_runtime_result.json"
    server_log = bundle_dir / "compare" / "server.log"
    pytest_log = bundle_dir / "compare" / "pytest.log"
    manifest_path = bundle_dir / "capstone_evidence_manifest.json"

    _write_json(eval_path, _make_eval_summary())
    _write_json(throughput_path, _make_throughput_result())
    _write_json(mic_path, _make_mic_latency_result())
    _write_json(live_path, _make_live_runtime_result())
    server_log.parent.mkdir(parents=True, exist_ok=True)
    server_log.write_text(server_log_text, encoding="utf-8")
    pytest_log.write_text(pytest_log_text, encoding="utf-8")

    proc = _run_assembler(
        "--output",
        str(manifest_path),
        "--evaluation-summary",
        str(eval_path),
        "--throughput-artifact",
        str(throughput_path),
        "--mic-latency-artifact",
        str(mic_path),
        "--live-runtime-artifact",
        str(live_path),
        "--compare-server-log",
        str(server_log),
        "--compare-pytest-log",
        str(pytest_log),
    )

    assert proc.returncode == 1
    manifest = _load_json(manifest_path)
    assert manifest["status"] == "error"
    assert manifest["phase"] == "compare_ui"
    assert manifest["error_stage"] == expected_error_stage
    assert manifest["phases"][-1]["name"] == "compare_ui"
    assert manifest["phases"][-1]["error_stage"] == expected_error_stage
