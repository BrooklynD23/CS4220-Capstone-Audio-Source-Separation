#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
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
FIXTURE_AUDIO_DIR = PROJECT_ROOT / "fixtures/audio"
FIXTURE_VIDEO_DIR = PROJECT_ROOT / "fixtures/video"
# Media discoverable under fixtures/audio and fixtures/video (lowercase suffix match).
_FIXTURE_AUDIO_EXTS = frozenset({".mp3", ".wav", ".flac", ".m4a", ".aac"})
_FIXTURE_VIDEO_EXTS = frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi"})
DEFAULT_MODEL = PROJECT_ROOT / "artifacts/models/umx-live.pt"
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8000
# CUDA 12.4 PyTorch wheels (needs an NVIDIA driver with CUDA 12.x support). Override with LAUNCH_PYTORCH_CUDA_INDEX.
DEFAULT_PYTORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu124"
# Optional second wheel index if primary leaves a CPU-only build (e.g. cu126). See LAUNCH_PYTORCH_CUDA_FALLBACK_INDEX.
BOX_INNER_WIDTH = 62


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


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def visible_len(s: str) -> int:
    return len(strip_ansi(s))


def pad_visible_right(s: str, width: int) -> str:
    n = visible_len(s)
    if n > width:
        plain = strip_ansi(s)
        if len(plain) > width:
            plain = plain[: max(0, width - 3)] + "..."
        return plain
    return s + (" " * (width - n))


def center_visible_plain(text: str, width: int) -> str:
    plain = text.strip()
    if len(plain) >= width:
        return plain[:width]
    pad = width - len(plain)
    left = pad // 2
    return " " * left + plain + " " * (width - len(plain) - left)


def box_row(inner: str) -> str:
    return f"│  {pad_visible_right(inner, BOX_INNER_WIDTH)} │"


def box_border_top() -> str:
    return f"┌{'─' * BOX_INNER_WIDTH}┐"


def box_border_bottom() -> str:
    return f"└{'─' * BOX_INNER_WIDTH}┘"


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


def _venv_can_import_torch(python: Path) -> bool:
    return (
        subprocess.run(
            [str(python), "-c", "import torch"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def pytorch_cuda_index() -> str:
    return (os.environ.get("LAUNCH_PYTORCH_CUDA_INDEX") or DEFAULT_PYTORCH_CUDA_INDEX).strip() or DEFAULT_PYTORCH_CUDA_INDEX


def pytorch_cuda_fallback_index() -> str | None:
    fb = (os.environ.get("LAUNCH_PYTORCH_CUDA_FALLBACK_INDEX") or "").strip()
    return fb or None


def uninstall_torch_family(python: Path) -> None:
    """Remove PyTorch packages so pip cannot leave a stale +cpu build."""
    for _ in range(4):
        if not _venv_can_import_torch(python):
            return
        subprocess.run(
            [str(python), "-m", "pip", "uninstall", "-y", "torch", "torchvision", "torchaudio"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def venv_torch_wheel_is_cuda_build(python: Path) -> bool:
    if not _venv_can_import_torch(python):
        return False
    code = "import torch,sys; sys.exit(0 if torch.version.cuda else 1)"
    return (
        subprocess.run(
            [str(python), "-c", code],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def try_install_cuda_torch_wheels(python: Path) -> bool:
    """Install CUDA torch/torchaudio from PyTorch wheel index only (no PyPI torch resolution)."""
    if os.environ.get("LAUNCH_SKIP_CUDA_TORCH", "").strip().lower() in ("1", "true", "yes"):
        return False
    if sys.platform == "darwin":
        return False

    indices: list[str] = [pytorch_cuda_index()]
    fb = pytorch_cuda_fallback_index()
    if fb and fb != indices[0]:
        indices.append(fb)

    for idx in indices:
        uninstall_torch_family(python)
        try:
            subprocess.run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "torch",
                    "torchaudio",
                    "--index-url",
                    idx,
                ],
                cwd=PROJECT_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            print(color("  CUDA PyTorch wheel install failed (GPU compare may be unavailable):", Colors.yellow), file=sys.stderr)
            if exc.stderr:
                print(exc.stderr, file=sys.stderr)
            continue
        if venv_torch_wheel_is_cuda_build(python):
            return True
        print(
            color(
                f"  PyTorch wheel from {idx} is still CPU-only; "
                "try LAUNCH_PYTORCH_CUDA_FALLBACK_INDEX or a newer NVIDIA driver (see nvidia-smi).",
                Colors.yellow,
            ),
            file=sys.stderr,
        )

    print(
        color(
            "  PyTorch remained CPU-only. Set LAUNCH_PYTORCH_CUDA_INDEX / LAUNCH_PYTORCH_CUDA_FALLBACK_INDEX "
            "to a cu12x line from https://pytorch.org/get-started/locally/",
            Colors.yellow,
        ),
        file=sys.stderr,
    )
    return False


def ensure_torch_torchaudio(python: Path) -> None:
    """Install torch+torchaudio from PyPI when CUDA wheels were skipped or failed (e.g. macOS, CPU-only)."""
    try:
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "torch",
                "torchaudio",
            ],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(color("  pip install torch torchaudio failed:", Colors.red), file=sys.stderr)
        print(exc.stderr, file=sys.stderr)
        raise


def torch_cuda_probe_line(python: Path) -> str:
    """One-line torch/CUDA build info for troubleshooting (no GPU required)."""
    code = (
        "import torch; "
        "v = getattr(torch.version, 'cuda', None) or 'None'; "
        "print(f'torch={torch.__version__} build_cuda={v} cuda.is_available()={torch.cuda.is_available()}')"
    )
    result = subprocess.run(
        [str(python), "-W", "ignore", "-c", code],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return (result.stdout or "").strip() or "(torch probe failed)"


def install_gpu_stack(python: Path) -> None:
    """Ensure launcher GPU deps (excluding PyAudio); install CUDA torch wheels on Windows/Linux when possible."""
    print_status("Installing GPU dependencies", "...")
    skip_cuda = os.environ.get("LAUNCH_SKIP_CUDA_TORCH", "").strip().lower() in ("1", "true", "yes")
    # Demucs/Open-Unmix may pull a CPU-only torch from PyPI. Install GPU packages first, then
    # always re-apply CUDA torch/audio on Windows/Linux so pip cannot leave a PyPI CPU build in place.
    if sys.platform == "darwin" or skip_cuda:
        if not _venv_can_import_torch(python):
            ensure_torch_torchaudio(python)

    try:
        subprocess.run(
            [str(python), "-m", "pip", "install", "-e", ".[gpu_launcher]"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(color("  pip install .[gpu_launcher] failed:", Colors.red), file=sys.stderr)
        print(exc.stderr, file=sys.stderr)
        raise

    if sys.platform != "darwin" and not skip_cuda:
        try_install_cuda_torch_wheels(python)
        if not _venv_can_import_torch(python):
            ensure_torch_torchaudio(python)

    print_status("Installing GPU dependencies", "✓")


def gpu_unavailable_help() -> str:
    probe = torch_cuda_probe_line(venv_python())
    return (
        f"GPU unavailable ({probe}). "
        "Requires NVIDIA GPU + working driver. If build_cuda=None, set LAUNCH_PYTORCH_CUDA_INDEX "
        "or LAUNCH_PYTORCH_CUDA_FALLBACK_INDEX (e.g. cu126 / cu128 per pytorch.org)."
    )


def option(label: str, key: str, selected: bool, available: bool = True, reason: str = "") -> str:
    text = f"({key}) {label}" if selected else f" {key}  {label}"
    if not available:
        shown = "—" if reason == "no CUDA" else reason
        return color(f"{text} [{shown}]", Colors.grey)
    if selected:
        return color(text, Colors.bright + Colors.cyan)
    return color(text, Colors.dim)


def source_default(source: str) -> Path:
    return DEFAULT_VIDEO_INPUT if source == "video-audio" else DEFAULT_MP3_INPUT


def _iter_fixture_media(root: Path, extensions: frozenset[str]) -> list[Path]:
    if not root.is_dir():
        return []
    discovered: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            discovered.append(path.resolve())
    return sorted(discovered, key=lambda p: str(p).lower())


def list_audio_fixtures() -> list[Path]:
    return _iter_fixture_media(FIXTURE_AUDIO_DIR, _FIXTURE_AUDIO_EXTS)


def list_video_fixtures() -> list[Path]:
    return _iter_fixture_media(FIXTURE_VIDEO_DIR, _FIXTURE_VIDEO_EXTS)


def source_mode_for_media_path(path: Path) -> str:
    return "video-audio" if path.suffix.lower() in _FIXTURE_VIDEO_EXTS else "mp3"


def default_dashboard_input() -> tuple[str, Path]:
    """First detected audio fixture, else bundled demo MP3."""
    audio = list_audio_fixtures()
    if audio:
        first = audio[0]
        return source_mode_for_media_path(first), first
    return "mp3", DEFAULT_MP3_INPUT.resolve()


def default_dashboard_device(cuda_available: bool) -> str:
    return "both" if cuda_available else "cpu"


def sanitize_run_label(path: Path) -> str:
    stem = path.stem
    safe = re.sub(r"[^\w\-.]+", "_", stem).strip("._") or "run"
    return safe[:48]


def make_both_mode_output_dirs(input_path: Path) -> tuple[Path, Path]:
    """Per-run CPU/GPU directories under artifacts/live/<label>-<utc-time>/."""
    label = sanitize_run_label(input_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = PROJECT_ROOT / "artifacts" / "live" / f"{label}-{stamp}"
    return base / "cpu", base / "gpu"


def prompt_for_fixture(current: Path) -> Path:
    """Pick a file under fixtures/audio or fixtures/video by number."""
    clear_screen()
    entries: list[tuple[str, Path]] = []
    for path in list_audio_fixtures():
        entries.append(("audio/mp3", path))
    for path in list_video_fixtures():
        entries.append(("video", path))

    if not entries:
        print(color("  No media files found under fixtures/audio or fixtures/video.", Colors.yellow))
        print("  Press Enter to continue.")
        input("  > ")
        return current

    while True:
        print("  Fixture media (relative to repo). Enter number, or blank to cancel:\n")
        width = max(2, len(str(len(entries))))
        for idx, (kind, path) in enumerate(entries, start=1):
            try:
                rel = path.relative_to(PROJECT_ROOT)
            except ValueError:
                rel = path
            print(f"  {idx:>{width}}  [{kind:11}]  {rel}")
        print()
        entered = input("  > ").strip()
        if not entered:
            return current
        if entered.isdigit():
            choice = int(entered)
            if 1 <= choice <= len(entries):
                return entries[choice - 1][1].resolve()
        clear_screen()
        print(color(f"  Invalid choice: {entered!r}\n", Colors.red))


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


def render_dashboard(
    settings: dict[str, object],
    model_available: bool,
    cuda_available: bool,
    message: str = "",
    *,
    cuda_probe_line: str = "",
) -> None:
    clear_screen()
    source = str(settings["source"])
    mode = str(settings["mode"])
    device = str(settings["device"])
    input_path = Path(str(settings["input"]))

    source_row = (
        "Source   "
        + option("MP3", "1", source == "mp3")
        + "  "
        + option("Video", "2", source == "video-audio")
        + "  "
        + option("Mic", "3", source == "mic")
    )
    input_row = "Input    " + short_path(input_path) + " [F]ile [L]ist"
    mode_row = (
        "Mode     "
        + option("Smoke", "A", mode == "smoke")
        + "  "
        + option("Full", "B", mode == "full", model_available, "no model")
    )
    device_row = (
        "Device   "
        + option("CPU", "X", device == "cpu")
        + "  "
        + option("GPU", "Y", device == "gpu", cuda_available, "no CUDA")
        + "  "
        + option("Both", "Z", device == "both", cuda_available, "no CUDA")
    )
    compare_hint = color("      L: pick fixture under fixtures/   Z: CPU+GPU (needs CUDA torch)", Colors.dim)
    divider_inner = " " + ("-" * (BOX_INNER_WIDTH - 2)) + " "

    smoke_gpu_hint = ""
    if mode == "smoke" and device in ("gpu", "both"):
        smoke_gpu_hint = color(
            pad_visible_right(
                "Smoke: not separated. Press B (Full) for 4-stem umxhq.",
                BOX_INNER_WIDTH,
            ),
            Colors.yellow,
        )

    probe_row = ""
    if not cuda_available and cuda_probe_line.strip():
        probe_row = color(
            pad_visible_right(cuda_probe_line.strip(), BOX_INNER_WIDTH),
            Colors.grey,
        )

    lines = [
        box_border_top(),
        box_row(center_visible_plain("Audio Source Separation Demo", BOX_INNER_WIDTH)),
        f"├{'─' * BOX_INNER_WIDTH}┤",
        box_row(""),
        box_row(source_row),
        box_row(input_row),
        box_row(mode_row),
        box_row(device_row),
        box_row(compare_hint),
    ]
    if smoke_gpu_hint:
        lines.append(box_row(smoke_gpu_hint))
    if probe_row:
        lines.append(box_row(probe_row))
    lines.extend(
        [
            box_row(""),
            box_row(divider_inner),
            box_row("R  Run     Q  Quit"),
            box_border_bottom(),
        ]
    )
    print("\n".join(lines))
    if message:
        print(f"\n  {message}")


# Room for "Input    " prefix and " [F]ile" suffix inside BOX_INNER_WIDTH
_INPUT_PATH_MAX = BOX_INNER_WIDTH - 9 - 7


def short_path(path: Path, max_len: int | None = None) -> str:
    try:
        value = str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        value = str(path)
    limit = _INPUT_PATH_MAX if max_len is None else max_len
    if len(value) > limit:
        return "..." + value[-(limit - 3) :]
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
    py = venv_python()
    cuda_probe_line = torch_cuda_probe_line(py) if py.exists() else "venv missing"
    initial_source, initial_input = default_dashboard_input()
    settings: dict[str, object] = {
        "source": initial_source,
        "input": initial_input,
        "mode": "smoke",
        "device": default_dashboard_device(cuda_available),
    }
    message = ""

    while True:
        render_dashboard(
            settings,
            model_available,
            cuda_available,
            message,
            cuda_probe_line=cuda_probe_line,
        )
        message = ""
        key = read_key().strip().lower()
        if key == "q":
            return None
        if key == "r":
            return settings
        if key == "1":
            settings["source"] = "mp3"
            audio = list_audio_fixtures()
            settings["input"] = audio[0] if audio else DEFAULT_MP3_INPUT
        elif key == "2":
            settings["source"] = "video-audio"
            video = list_video_fixtures()
            settings["input"] = video[0] if video else DEFAULT_VIDEO_INPUT
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
                message = gpu_unavailable_help()
        elif key == "z":
            if cuda_available:
                settings["device"] = "both"
            else:
                message = "CPU+GPU compare: " + gpu_unavailable_help()
        elif key == "f":
            settings["input"] = prompt_for_file(Path(str(settings["input"])))
        elif key == "l":
            picked = prompt_for_fixture(Path(str(settings["input"])))
            settings["input"] = picked
            if str(settings["source"]) != "mic":
                settings["source"] = source_mode_for_media_path(picked)
        else:
            message = "Choose one of 1/2/3, A/B, X/Y/Z, F, L, R, or Q."


def setup_environment() -> Path:
    python = venv_python()
    created = not python.exists()
    if created:
        print_status("Setting up environment", "creating .venv")
        subprocess.run([system_python(), "-m", "venv", str(PROJECT_ROOT / ".venv")], cwd=PROJECT_ROOT, check=True)
    else:
        print_status("Setting up environment", "reusing .venv")

    try:
        subprocess.run(
            [str(python), "-m", "pip", "install", "-e", ".[dev]"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        install_gpu_stack(python)
    except subprocess.CalledProcessError as exc:
        print(color("  pip install failed:", Colors.red), file=sys.stderr)
        print(exc.stderr, file=sys.stderr)
        raise

    skip_cuda = os.environ.get("LAUNCH_SKIP_CUDA_TORCH", "").strip().lower() in ("1", "true", "yes")
    if sys.platform != "darwin" and not skip_cuda and not check_cuda_available():
        print(
            color(f"  GPU runtime inactive — {torch_cuda_probe_line(python)}", Colors.yellow),
            flush=True,
        )
        print(
            color(
                "  Check NVIDIA driver (nvidia-smi). If build_cuda=None, PyTorch is CPU-only.",
                Colors.grey,
            ),
            flush=True,
        )

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


CAPSTONE_MANIFEST = PROJECT_ROOT / "artifacts" / "bench" / "capstone_evidence_manifest.json"


def encoded_artifact(path: Path) -> str:
    from urllib.parse import quote

    relative = path.resolve().relative_to(PROJECT_ROOT)
    return "/" + quote(relative.as_posix(), safe="/")


def browser_url(
    bind: str,
    port: int,
    artifact: Path,
    artifact2: Path | None = None,
    benchmark: Path | None = None,
) -> str:
    query = f"artifact={encoded_artifact(artifact)}"
    if artifact2 is not None:
        query += f"&artifact2={encoded_artifact(artifact2)}"
    if benchmark is not None:
        query += f"&benchmark={encoded_artifact(benchmark)}"
    return f"http://{bind}:{port}/ui/compare/?{query}"


def build_compare_url(
    artifact: Path,
    artifact2: Path | None,
    *,
    bind_host: str = DEFAULT_BIND,
    port: int = DEFAULT_PORT,
    benchmark: Path | None = None,
) -> str:
    return browser_url(bind_host, port, artifact, artifact2, benchmark)


def open_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception as exc:  # pragma: no cover - platform dependent
        print(color(f"  Browser open failed: {exc}", Colors.yellow))


def serve_compare(python: Path, args: argparse.Namespace, artifact: Path, artifact2: Path | None) -> int:
    benchmark_path = CAPSTONE_MANIFEST if CAPSTONE_MANIFEST.exists() else None
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
    if benchmark_path is not None:
        command.extend(["--benchmark", str(benchmark_path)])

    url = browser_url(args.ui_bind, args.ui_port, artifact, artifact2, benchmark_path)
    print_status("Opening browser", f"→ {url}")
    open_browser(url)
    print("  Press Ctrl+C to stop the server.")
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


def run_flow(settings: dict[str, object], args: argparse.Namespace, python: Path) -> int:
    clear_screen()
    selected_device = str(settings["device"])

    if selected_device == "both":
        cpu_dir, gpu_dir = make_both_mode_output_dirs(Path(str(settings["input"])))
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
    started = time.monotonic()
    try:
        python = setup_environment()
    except subprocess.CalledProcessError:
        return 1
    settings = run_dashboard(args)
    if settings is None:
        print("  Quit.")
        return 0
    try:
        return run_flow(settings, args, python)
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1
    except KeyboardInterrupt:
        elapsed = time.monotonic() - started
        print(f"\n  Stopped after {elapsed:.1f}s.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
