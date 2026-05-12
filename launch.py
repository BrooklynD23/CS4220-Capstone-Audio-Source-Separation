#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import webbrowser

try:
    import msvcrt
except ImportError:  # pragma: no cover - Windows only
    msvcrt = None

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - Unix only
    termios = None
    tty = None


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_MP3_INPUT = PROJECT_ROOT / "fixtures/audio/demo_mix.mp3"
DEFAULT_VIDEO_INPUT = PROJECT_ROOT / "fixtures/video/demo_mix.mp4"
DEFAULT_MODEL = PROJECT_ROOT / "artifacts/models/umx-live.pt"
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8000


@dataclass
class LauncherState:
    source_mode: str = "mp3"
    input_path: Path = DEFAULT_MP3_INPUT
    runtime_mode: str = "smoke"
    device: str = "cpu"


@dataclass(frozen=True)
class RunSpec:
    device: str
    output_dir: Path

    @property
    def artifact_path(self) -> Path:
        return self.output_dir / "live_runtime_result.json"


class Colors:
    reset = "\033[0m"
    bright = "\033[1m"
    dim = "\033[2m"
    cyan = "\033[36m"
    green = "\033[32m"
    yellow = "\033[33m"
    red = "\033[31m"
    grey = "\033[90m"


def supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


COLOR = supports_color()


def color(text: str, code: str) -> str:
    return f"{code}{text}{Colors.reset}" if COLOR else text


def clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def venv_python() -> Path:
    if os.name == "nt":
        return PROJECT_ROOT / ".venv/Scripts/python.exe"
    return PROJECT_ROOT / ".venv/bin/python"


def system_python() -> str:
    return sys.executable or shutil.which("python3") or shutil.which("python") or "python"


def read_key() -> str:
    if msvcrt is not None:  # pragma: no cover - Windows only
        return msvcrt.getwch()
    if termios is None or tty is None or not sys.stdin.isatty():
        return sys.stdin.readline()[:1]

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def check_cuda_available() -> bool:
    python = venv_python()
    if not python.exists():
        return False
    code = "import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)"
    result = subprocess.run(
        [str(python), "-c", code],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def option(label: str, key: str, selected: bool, available: bool = True, reason: str = "") -> str:
    text = f"({key}) {label}" if selected else f" {key}  {label}"
    if not available:
        return color(f"{text} [{reason}]", Colors.grey)
    if selected:
        return color(text, Colors.bright + Colors.cyan)
    return color(text, Colors.dim)


def source_default(source: str) -> Path:
    return DEFAULT_VIDEO_INPUT if source == "video-audio" else DEFAULT_MP3_INPUT


def build_run_spec(device: str, output_dir: Path) -> RunSpec:
    return RunSpec(device=device, output_dir=output_dir)


def build_run_command(python: Path, state: LauncherState, spec: RunSpec) -> list[str]:
    command = [
        str(python),
        str(PROJECT_ROOT / "scripts/live/run_live_separation.py"),
        "--source-mode",
        state.source_mode,
        "--output-dir",
        str(spec.output_dir),
        "--artifact-path",
        str(spec.artifact_path),
        "--mode",
        state.runtime_mode,
        "--device-requested",
        spec.device,
        "--device-used",
        spec.device,
        "--mic-backend",
        "fake",
    ]
    if state.source_mode != "mic":
        command.extend(["--input", str(state.input_path)])
    return command


def render_dashboard(settings: dict[str, object], model_available: bool, cuda_available: bool, message: str = "") -> None:
    clear_screen()
    source = str(settings["source"])
    mode = str(settings["mode"])
    device = str(settings["device"])
    input_path = Path(str(settings["input"]))

    lines = [
        "┌──────────────────────────────────────────────────────────────┐",
        "│              Audio Source Separation Demo                    │",
        "├──────────────────────────────────────────────────────────────┤",
        "│                                                              │",
        f"│  Source   {option('MP3', '1', source == 'mp3')}   {option('Video', '2', source == 'video-audio')}   {option('Mic', '3', source == 'mic')}      │",
        f"│  Input    {short_path(input_path):<42} [F]ile   │",
        f"│  Mode     {option('Smoke', 'A', mode == 'smoke')}   {option('Full', 'B', mode == 'full', model_available, 'no model')}              │",
        f"│  Device   {option('CPU', 'X', device == 'cpu')}   {option('GPU', 'Y', device == 'gpu', cuda_available, 'no CUDA')}   {option('Both', 'Z', device == 'both', cuda_available, 'no CUDA')} ◄ compare │",
        "│                                                              │",
        "│  ----------------------------------------------------------  │",
        "│  R  Run     Q  Quit                                          │",
        "└──────────────────────────────────────────────────────────────┘",
    ]
    print("\n".join(lines))
    if message:
        print(f"\n  {message}")


def short_path(path: Path) -> str:
    try:
        value = str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        value = str(path)
    if len(value) > 42:
        return "..." + value[-39:]
    return value


def prompt_for_file(current: Path) -> Path:
    clear_screen()
    while True:
        print("  Enter path to audio or video file (Enter to cancel):")
        entered = input("  > ").strip()
        if not entered:
            return current
        candidate = Path(entered).expanduser()
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
        clear_screen()
        print(color(f"  File not found: {entered}\n", Colors.red))


def run_dashboard(args: argparse.Namespace) -> dict[str, object] | None:
    model_available = DEFAULT_MODEL.exists()
    cuda_available = check_cuda_available()
    settings: dict[str, object] = {
        "source": "mp3",
        "input": DEFAULT_MP3_INPUT,
        "mode": "smoke",
        "device": "cpu",
    }
    message = ""

    while True:
        render_dashboard(settings, model_available, cuda_available, message)
        message = ""
        key = read_key().strip().lower()
        if key == "q":
            return None
        if key == "r":
            return settings
        if key == "1":
            settings["source"] = "mp3"
            settings["input"] = DEFAULT_MP3_INPUT
        elif key == "2":
            settings["source"] = "video-audio"
            settings["input"] = DEFAULT_VIDEO_INPUT
        elif key == "3":
            settings["source"] = "mic"
        elif key == "a":
            settings["mode"] = "smoke"
        elif key == "b":
            if model_available:
                settings["mode"] = "full"
            else:
                message = "Full mode is unavailable because artifacts/models/umx-live.pt is missing."
        elif key == "x":
            settings["device"] = "cpu"
        elif key == "y":
            if cuda_available:
                settings["device"] = "gpu"
            else:
                message = "GPU is unavailable because CUDA was not detected in .venv."
        elif key == "z":
            if cuda_available:
                settings["device"] = "both"
            else:
                message = "CPU+GPU compare is unavailable because CUDA was not detected in .venv."
        elif key == "f":
            settings["input"] = prompt_for_file(Path(str(settings["input"])))
        else:
            message = "Choose one of 1/2/3, A/B, X/Y/Z, F, R, or Q."


def setup_environment() -> Path:
    python = venv_python()
    if python.exists():
        print_status("Setting up environment", "reusing .venv")
        return python

    print_status("Setting up environment", "creating .venv")
    subprocess.run([system_python(), "-m", "venv", str(PROJECT_ROOT / ".venv")], cwd=PROJECT_ROOT, check=True)
    try:
        subprocess.run(
            [str(python), "-m", "pip", "install", "-e", ".[dev]"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(color("  pip install failed:", Colors.red), file=sys.stderr)
        print(exc.stderr, file=sys.stderr)
        raise
    print_status("Setting up environment", "✓")
    return python


def print_status(label: str, detail: str) -> None:
    print(f"  {label:<38} {detail}", flush=True)


def artifact_path(output_dir: Path) -> Path:
    return output_dir / "live_runtime_result.json"


def run_separation(
    python: Path,
    *,
    settings: dict[str, object],
    device: str,
    output_dir: Path,
) -> tuple[int, dict[str, object] | None, str]:
    state = LauncherState(
        source_mode=str(settings["source"]),
        input_path=Path(str(settings["input"])),
        runtime_mode=str(settings["mode"]),
        device=device,
    )
    artifact = artifact_path(output_dir)
    command = build_run_command(python, state, build_run_spec(device, output_dir))

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    payload = load_artifact(artifact)
    return result.returncode, payload, (result.stderr or result.stdout).strip()


def load_artifact(path: Path) -> dict[str, object] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def total_ms(payload: dict[str, object] | None) -> float:
    value = payload.get("total_ms") if payload else None
    return float(value) if isinstance(value, (int, float)) else 0.0


def infer_ms(payload: dict[str, object] | None) -> float:
    value = payload.get("infer_ms") if payload else None
    return float(value) if isinstance(value, (int, float)) else 0.0


def error_message(payload: dict[str, object] | None, fallback: str) -> str:
    value = payload.get("error_message") if payload else None
    return str(value) if value else fallback or "GPU run failed"


def encoded_artifact(path: Path) -> str:
    from urllib.parse import quote

    relative = path.resolve().relative_to(PROJECT_ROOT)
    return "/" + quote(relative.as_posix(), safe="/")


def browser_url(bind: str, port: int, artifact: Path, artifact2: Path | None = None) -> str:
    query = f"artifact={encoded_artifact(artifact)}"
    if artifact2 is not None:
        query += f"&artifact2={encoded_artifact(artifact2)}"
    return f"http://{bind}:{port}/ui/compare/?{query}"


def build_compare_url(
    artifact: Path,
    artifact2: Path | None,
    *,
    bind_host: str = DEFAULT_BIND,
    port: int = DEFAULT_PORT,
) -> str:
    return browser_url(bind_host, port, artifact, artifact2)


def open_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception as exc:  # pragma: no cover - platform dependent
        print(color(f"  Browser open failed: {exc}", Colors.yellow))


def serve_compare(python: Path, args: argparse.Namespace, artifact: Path, artifact2: Path | None) -> int:
    command = [
        str(python),
        str(PROJECT_ROOT / "scripts/ui/serve_compare_demo.py"),
        "--bind",
        args.ui_bind,
        "--port",
        str(args.ui_port),
        "--directory",
        str(PROJECT_ROOT),
        "--artifact",
        str(artifact),
    ]
    if artifact2 is not None:
        command.extend(["--artifact2", str(artifact2)])

    url = browser_url(args.ui_bind, args.ui_port, artifact, artifact2)
    print_status("Opening browser", f"→ {url}")
    open_browser(url)
    print("  Press Ctrl+C to stop the server.")
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


def run_flow(settings: dict[str, object], args: argparse.Namespace) -> int:
    clear_screen()
    python = setup_environment()
    selected_device = str(settings["device"])

    if selected_device == "both":
        cpu_dir = PROJECT_ROOT / "artifacts/live/cpu-run"
        gpu_dir = PROJECT_ROOT / "artifacts/live/gpu-run"
        print_status("Running CPU separation", "...")
        cpu_code, cpu_payload, cpu_output = run_separation(
            python,
            settings=settings,
            device="cpu",
            output_dir=cpu_dir,
        )
        if cpu_code != 0 or not cpu_payload or cpu_payload.get("status") == "error":
            print(color(f"  CPU run failed: {error_message(cpu_payload, cpu_output)}", Colors.red), file=sys.stderr)
            return cpu_code or 1
        print_status("Running CPU separation", f"✓  {total_ms(cpu_payload):.0f} ms")

        print_status("Running GPU separation", "...")
        gpu_code, gpu_payload, gpu_output = run_separation(
            python,
            settings=settings,
            device="gpu",
            output_dir=gpu_dir,
        )
        gpu_ok = gpu_code == 0 and bool(gpu_payload) and gpu_payload.get("status") != "error"
        if gpu_ok:
            print_status("Running GPU separation", f"✓  {total_ms(gpu_payload):.0f} ms")
            cpu_infer = infer_ms(cpu_payload)
            gpu_infer = infer_ms(gpu_payload)
            speedup = (cpu_infer / gpu_infer) if gpu_infer > 0 else 0.0
            print("  ---------------------------------------------------------")
            print(f"  GPU is {speedup:.1f}x faster  (infer: {cpu_infer:.0f} ms -> {gpu_infer:.0f} ms)")
            print("  ---------------------------------------------------------")
            return serve_compare(python, args, artifact_path(cpu_dir), artifact_path(gpu_dir))

        print(color(f"  GPU run failed: {error_message(gpu_payload, gpu_output)}", Colors.yellow))
        print(color("  Continuing with CPU-only results.", Colors.yellow))
        return serve_compare(python, args, artifact_path(cpu_dir), None)

    output_dir = PROJECT_ROOT / "artifacts/live/one-click"
    label = "CPU" if selected_device == "cpu" else "GPU"
    print_status(f"Running {label} separation", "...")
    code, payload, output = run_separation(
        python,
        settings=settings,
        device=selected_device,
        output_dir=output_dir,
    )
    if code != 0 or not payload or payload.get("status") == "error":
        print(color(f"  {label} run failed: {error_message(payload, output)}", Colors.red), file=sys.stderr)
        return code or 1
    print_status(f"Running {label} separation", f"✓  {total_ms(payload):.0f} ms")
    return serve_compare(python, args, artifact_path(output_dir), None)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive local demo launcher.")
    parser.add_argument("--ui-bind", default=DEFAULT_BIND, help=f"UI bind address (default: {DEFAULT_BIND})")
    parser.add_argument("--ui-port", type=int, default=DEFAULT_PORT, help=f"UI port (default: {DEFAULT_PORT})")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    settings = run_dashboard(args)
    if settings is None:
        print("  Quit.")
        return 0
    started = time.monotonic()
    try:
        return run_flow(settings, args)
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1
    except KeyboardInterrupt:
        elapsed = time.monotonic() - started
        print(f"\n  Stopped after {elapsed:.1f}s.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
