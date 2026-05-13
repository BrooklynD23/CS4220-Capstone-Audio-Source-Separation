from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ui import serve_compare_demo


class _FakeHTTPServer:
    def __init__(self, address, handler):
        self.server_address = address
        self.handler = handler

    def serve_forever(self):
        raise KeyboardInterrupt

    def server_close(self):
        pass


def test_build_compare_url_includes_both_artifacts():
    url = serve_compare_demo._build_compare_url(
        "127.0.0.1",
        8000,
        "/artifacts/live/cpu%20run/live_runtime_result.json",
        "/artifacts/live/gpu%20run/live_runtime_result.json",
    )

    assert url == (
        "http://127.0.0.1:8000/ui/compare/"
        "?artifact=/artifacts/live/cpu%20run/live_runtime_result.json"
        "&artifact2=/artifacts/live/gpu%20run/live_runtime_result.json"
    )


def test_main_prints_single_or_dual_compare_url(monkeypatch, capsys):
    monkeypatch.setattr(serve_compare_demo, "ThreadingHTTPServer", _FakeHTTPServer)
    monkeypatch.setattr(serve_compare_demo.CompareDemoHandler, "log_message", lambda self, format, *args: None)

    artifact = PROJECT_ROOT / "artifacts" / "live" / "cpu run" / "live_runtime_result.json"
    artifact2 = PROJECT_ROOT / "artifacts" / "live" / "gpu run" / "live_runtime_result.json"

    exit_code = serve_compare_demo.main([
        "--directory",
        str(PROJECT_ROOT),
        "--artifact",
        str(artifact),
        "--artifact2",
        str(artifact2),
    ])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "?artifact=/artifacts/live/cpu%20run/live_runtime_result.json" in out
    assert "&artifact2=/artifacts/live/gpu%20run/live_runtime_result.json" in out

    exit_code_single = serve_compare_demo.main([
        "--directory",
        str(PROJECT_ROOT),
        "--artifact",
        str(artifact),
    ])
    out_single = capsys.readouterr().out
    assert exit_code_single == 0
    assert "?artifact=/artifacts/live/cpu%20run/live_runtime_result.json" in out_single
    assert "artifact2=" not in out_single


def test_main_prints_benchmark_query_when_flag_passed(monkeypatch, capsys):
    monkeypatch.setattr(serve_compare_demo, "ThreadingHTTPServer", _FakeHTTPServer)
    monkeypatch.setattr(serve_compare_demo.CompareDemoHandler, "log_message", lambda self, format, *args: None)

    artifact = PROJECT_ROOT / "artifacts" / "live" / "cpu run" / "live_runtime_result.json"
    bench = PROJECT_ROOT / "tests" / "fixtures" / "ui" / "compare" / "benchmark_evidence_mini.json"

    exit_code = serve_compare_demo.main([
        "--directory",
        str(PROJECT_ROOT),
        "--artifact",
        str(artifact),
        "--benchmark",
        str(bench),
    ])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "benchmark=" in out
    assert "benchmark_evidence_mini.json" in out


def test_main_rejects_artifact2_outside_project_root(tmp_path, capsys):
    outside = tmp_path.parent / "outside" / "bad.json"

    exit_code = serve_compare_demo.main([
        "--directory",
        str(PROJECT_ROOT),
        "--artifact",
        str(PROJECT_ROOT / "artifacts/live/one-click/live_runtime_result.json"),
        "--artifact2",
        str(outside),
    ])

    err = capsys.readouterr().err
    assert exit_code == 2
    assert "invalid artifact path" in err
