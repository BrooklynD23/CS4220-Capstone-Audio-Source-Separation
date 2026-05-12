from __future__ import annotations

from pathlib import Path

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
