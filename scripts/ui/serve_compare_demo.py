from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tempfile
import uuid
import wave
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ui.encode_artifact_path import encode_artifact_path

DEFAULT_DIRECTORY = PROJECT_ROOT
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

_SEPARATOR_CACHE: dict[str, Any] = {}


def _parse_multipart(
    rfile: io.RawIOBase,
    content_type: str,
    content_length: int,
) -> dict[str, Any]:
    """Parse a multipart/form-data body without the deprecated cgi module.

    Returns a dict mapping field name -> bytes (for file fields) or str (for
    plain text fields).  Raises ValueError on malformed input.
    """
    m = re.search(r"boundary=([^\s;]+)", content_type)
    if not m:
        raise ValueError("Missing boundary in Content-Type")
    boundary = m.group(1).strip('"')

    raw = rfile.read(content_length)
    sep = (f"--{boundary}").encode()

    fields: dict[str, Any] = {}
    parts = raw.split(sep)
    for part in parts:
        part = part.strip(b"\r\n")
        if not part or part == b"--" or part.startswith(b"--"):
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_block, _, body = part.partition(b"\r\n\r\n")
        # Strip trailing boundary markers from body
        body = body.rstrip(b"\r\n")

        headers: dict[str, str] = {}
        for line in header_block.decode("utf-8", errors="replace").splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                headers[k.strip().lower()] = v.strip()

        cd = headers.get("content-disposition", "")
        name_m = re.search(r'name="([^"]*)"', cd)
        if not name_m:
            continue
        name = name_m.group(1)

        filename_m = re.search(r'filename="([^"]*)"', cd)
        if filename_m:
            # Store file fields as a simple namespace with .file and .filename
            fields[name] = _FileField(filename=filename_m.group(1), data=body)
        else:
            fields[name] = body.decode("utf-8", errors="replace")

    return fields


class _FileField:
    """Minimal file-like container returned by _parse_multipart for file fields."""

    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self.file: io.BytesIO = io.BytesIO(data)


def _encode_compare_artifact(artifact: str | None) -> str | None:
    if artifact is None:
        return None
    return encode_artifact_path(str(PROJECT_ROOT), artifact)


def _build_compare_url(host: str, port: int, artifact: str | None, artifact2: str | None) -> str:
    query_parts = []
    if artifact is not None:
        query_parts.append(f"artifact={artifact}")
    if artifact2 is not None:
        query_parts.append(f"artifact2={artifact2}")
    query = "&".join(query_parts)
    return urlunsplit(("http", f"{host}:{port}", "/ui/compare/", query, ""))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def _run_separation(mp3_bytes: bytes, device_str: str, project_root: Path) -> dict[str, Any]:
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from live_runtime import umx_separator
    from live_runtime.mp3_ingest import decode_audio_to_pcm
    from live_runtime.stem_router import write_live_stems_from_arrays

    device = umx_separator.resolve_device(device_str)

    if device not in _SEPARATOR_CACHE:
        _SEPARATOR_CACHE[device] = umx_separator.load_umxhq_separator(device)
    separator = _SEPARATOR_CACHE[device]

    run_id = uuid.uuid4().hex[:8]
    output_dir = project_root / "artifacts" / "live" / f"demo-{run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    mp3_path = output_dir / "input.mp3"
    mp3_path.write_bytes(mp3_bytes)

    decoded = decode_audio_to_pcm(mp3_path, target_sample_rate_hz=44100, chunk_duration_s=0.5)

    audio_tensor = umx_separator.pcm_to_tensor(decoded.pcm)
    sep = umx_separator.separate_tensor(audio_tensor, decoded.sample_rate_hz, separator, device)

    mix_path = output_dir / "mix.wav"
    with wave.open(str(mix_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(decoded.sample_rate_hz)
        wf.writeframes(decoded.pcm)

    routing = write_live_stems_from_arrays(sep.stems, output_dir, sep.sample_rate_hz)

    device_used = "gpu" if device == "cuda" else device
    artifact_path = output_dir / "live_runtime_result.json"
    _write_json_atomic(artifact_path, {
        "status": "ok",
        "input": str(mp3_path),
        "timestamp": datetime.now(UTC).isoformat(),
        "stft_ms": sep.timings.stft_ms,
        "infer_ms": sep.timings.infer_ms,
        "istft_ms": sep.timings.istft_ms,
        "total_ms": sep.timings.total_ms,
        "device_used": device_used,
        "sample_rate_hz": sep.sample_rate_hz,
    })

    def rel(p: Path) -> str:
        return str(p.relative_to(project_root)).replace("\\", "/")

    return {
        "artifact_path": rel(artifact_path),
        "stem_urls": {
            "input":  rel(mix_path),
            "vocals": rel(Path(routing.vocals_path)),
            "drums":  rel(Path(routing.drums_path)),
            "bass":   rel(Path(routing.bass_path)),
            "other":  rel(Path(routing.other_path)),
        },
        "timings": {
            "stft_ms":  sep.timings.stft_ms,
            "infer_ms": sep.timings.infer_ms,
            "istft_ms": sep.timings.istft_ms,
            "total_ms": sep.timings.total_ms,
        },
        "device_used": device_used,
    }


class CompareDemoHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        message = format % args
        print(f"compare-demo: {self.client_address[0]} {message}", file=sys.stderr)

    def do_POST(self) -> None:
        if self.path != "/api/separate":
            self._send_json(404, {"error": "Not Found"})
            return

        try:
            content_length = max(0, int(self.headers.get("Content-Length", "0")))
        except (ValueError, TypeError):
            self._send_json(400, {"error": "Invalid Content-Length"})
            return
        if content_length > MAX_UPLOAD_BYTES:
            self._send_json(413, {"error": "File too large (max 50 MB)"})
            return

        content_type = self.headers.get("Content-Type", "")
        try:
            form = _parse_multipart(self.rfile, content_type, content_length)
        except Exception as exc:
            self._send_json(400, {"error": f"Failed to parse request: {exc}"})
            return

        if "file" not in form:
            self._send_json(400, {"error": "Missing file field"})
            return

        file_item = form["file"]
        if not isinstance(file_item, _FileField):
            self._send_json(400, {"error": "Missing file field"})
            return

        device_str = (form.get("device") or "gpu")
        if not isinstance(device_str, str):
            device_str = "gpu"
        mp3_bytes = file_item.file.read()

        try:
            result = _run_separation(mp3_bytes, device_str, Path(self.directory))
            self._send_json(200, result)
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the compare UI from a local static root.")
    parser.add_argument("--bind", default=DEFAULT_BIND,
                        help=f"Interface to bind to (default: {DEFAULT_BIND})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Port to listen on (default: {DEFAULT_PORT})")
    parser.add_argument("--directory", default=str(DEFAULT_DIRECTORY),
                        help="Directory to serve (default: repository root)")
    parser.add_argument(
        "--artifact",
        default=None,
        help="Optional artifact path to preload in the compare UI (must live inside the project root).",
    )
    parser.add_argument(
        "--artifact2",
        default=None,
        help="Optional second artifact path to preload in the compare UI (must live inside the project root).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    directory = Path(args.directory).resolve()

    try:
        artifact = _encode_compare_artifact(args.artifact)
        artifact2 = _encode_compare_artifact(args.artifact2)
    except ValueError as exc:
        print(f"compare-demo: invalid artifact path — {exc}", file=sys.stderr)
        return 2

    if not directory.exists():
        print(f"compare-demo: directory not found: {directory}", file=sys.stderr)
        return 2
    if not directory.is_dir():
        print(f"compare-demo: directory is not a directory: {directory}", file=sys.stderr)
        return 2

    handler = partial(CompareDemoHandler, directory=str(directory))

    try:
        server = ThreadingHTTPServer((args.bind, args.port), handler)
    except OSError as exc:
        print(f"compare-demo: failed to bind {args.bind}:{args.port} — {exc}", file=sys.stderr)
        return 3

    host, port = server.server_address[:2]
    compare_url = _build_compare_url(str(host), port, artifact, artifact2)
    print(f"compare-demo: serving {directory} at {compare_url}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("compare-demo: shutdown requested", file=sys.stderr)
    finally:
        server.server_close()
        print("compare-demo: stopped", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
