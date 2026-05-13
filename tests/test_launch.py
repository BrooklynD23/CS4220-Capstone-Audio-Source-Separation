from __future__ import annotations

from pathlib import Path

import pytest

import launch
from launch import LauncherState, build_compare_url, build_run_command, build_run_spec


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_build_compare_url_encodes_single_and_dual_artifacts() -> None:
    single = build_compare_url(
        PROJECT_ROOT / "artifacts/live/one-click/live_runtime_result.json",
        None,
        bind_host="127.0.0.1",
        port=8000,
    )
    dual = build_compare_url(
        PROJECT_ROOT / "artifacts/live/cpu-run/live runtime result.json",
        PROJECT_ROOT / "artifacts/live/gpu-run/live runtime result.json",
        bind_host="127.0.0.1",
        port=8000,
    )

    assert single == "http://127.0.0.1:8000/ui/compare/?artifact=/artifacts/live/one-click/live_runtime_result.json"
    assert dual == (
        "http://127.0.0.1:8000/ui/compare/"
        "?artifact=/artifacts/live/cpu-run/live%20runtime%20result.json"
        "&artifact2=/artifacts/live/gpu-run/live%20runtime%20result.json"
    )


def test_build_compare_url_encodes_benchmark_query_param() -> None:
    bench = PROJECT_ROOT / "tests/fixtures/ui/compare/benchmark_evidence_mini.json"
    url = build_compare_url(
        PROJECT_ROOT / "artifacts/live/one-click/live_runtime_result.json",
        None,
        bind_host="127.0.0.1",
        port=8000,
        benchmark=bench,
    )
    assert "artifact=/artifacts/live/one-click/live_runtime_result.json" in url
    assert "benchmark=" in url
    assert "benchmark_evidence_mini.json" in url


def test_build_run_command_includes_input_only_for_file_sources(tmp_path: Path) -> None:
    venv_python = Path("/tmp/venv/bin/python")
    spec = build_run_spec("cpu", tmp_path / "out")
    state = LauncherState()
    command = build_run_command(venv_python, state, spec)

    assert command[:2] == [str(venv_python), str(PROJECT_ROOT / "scripts/live/run_live_separation.py")]
    assert "--input" in command

    state.source_mode = "mic"
    mic_command = build_run_command(venv_python, state, spec)
    assert "--input" not in mic_command


def test_list_audio_fixtures_respects_directory_and_extensions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    audio_root = tmp_path / "fixtures_audio"
    audio_root.mkdir()
    (audio_root / "clip.mp3").write_bytes(b"x")
    (audio_root / "skip.txt").write_text("no")
    sub = audio_root / "nested"
    sub.mkdir()
    (sub / "inner.wav").write_bytes(b"x")

    monkeypatch.setattr(launch, "FIXTURE_AUDIO_DIR", audio_root)
    found = launch.list_audio_fixtures()
    assert len(found) == 2
    assert {p.name for p in found} == {"clip.mp3", "inner.wav"}


def test_list_video_fixtures_respects_extensions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    video_root = tmp_path / "fixtures_video"
    video_root.mkdir()
    (video_root / "a.mp4").write_bytes(b"x")
    (video_root / "b.MKV").write_bytes(b"x")

    monkeypatch.setattr(launch, "FIXTURE_VIDEO_DIR", video_root)
    found = launch.list_video_fixtures()
    assert len(found) == 2


def test_source_mode_for_media_path() -> None:
    assert launch.source_mode_for_media_path(Path("x.mp3")) == "mp3"
    assert launch.source_mode_for_media_path(Path(r"Z:\foo\bar.MP4")) == "video-audio"


def test_default_dashboard_device() -> None:
    assert launch.default_dashboard_device(False) == "cpu"
    assert launch.default_dashboard_device(True) == "both"


def test_sanitize_run_label() -> None:
    assert launch.sanitize_run_label(Path("nice-track.mp3")) == "nice-track"
    assert len(launch.sanitize_run_label(Path("a" * 80 + ".mp3"))) == 48


def test_make_both_mode_output_dirs_layout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_root = tmp_path / "repo"
    fake_root.mkdir()
    monkeypatch.setattr(launch, "PROJECT_ROOT", fake_root.resolve())
    cpu_dir, gpu_dir = launch.make_both_mode_output_dirs(Path("demo_mix.mp3"))
    assert cpu_dir.name == "cpu"
    assert gpu_dir.name == "gpu"
    assert cpu_dir.parent == gpu_dir.parent
    assert cpu_dir.parent.parent == fake_root.resolve() / "artifacts" / "live"
