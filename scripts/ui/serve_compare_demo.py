from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import uuid
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


def _build_compare_url(
    host: str,
    port: int,
    artifact: str | None,
    artifact2: str | None,
    benchmark: str | None = None,
) -> str:
    query_parts = []
    if artifact is not None:
        query_parts.append(f"artifact={artifact}")
    if artifact2 is not None:
        query_parts.append(f"artifact2={artifact2}")
    if benchmark is not None:
        query_parts.append(f"benchmark={benchmark}")
    query = "&".join(query_parts)
    return urlunsplit(("http", f"{host}:{port}", "/ui/compare/", query, ""))


def _run_separation(
    media_bytes: bytes,
    device_str: str,
    project_root: Path,
    original_filename: str,
) -> dict[str, Any]:
    """Run `scripts/live/run_live_separation.py` so the written JSON matches live-runtime schema."""
    root = project_root.resolve()
    run_id = uuid.uuid4().hex[:8]
    output_dir = (root / "artifacts" / "live" / f"demo-{run_id}").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(original_filename or "upload").name
    suffix = Path(safe_name).suffix.lower()
    allowed = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".mp4", ".webm", ".mov"}
    if suffix not in allowed:
        suffix = ".mp3"
    input_media = (output_dir / f"input{suffix}").resolve()
    input_media.write_bytes(media_bytes)

    dev = (device_str or "cpu").strip().lower()
    device_flag = "gpu" if dev in ("cuda", "gpu") else "cpu"

    artifact_path = output_dir / "live_runtime_result.json"
    cli = [
        sys.executable,
        str(root / "scripts" / "live" / "run_live_separation.py"),
        "--source-mode",
        "mp3",
        "--input",
        str(input_media),
        "--output-dir",
        str(output_dir),
        "--artifact-path",
        str(artifact_path),
        "--mode",
        "smoke",
        "--device-requested",
        device_flag,
        "--device-used",
        device_flag,
        "--mic-backend",
        "fake",
    ]
    proc = subprocess.run(
        cli,
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or f"separation exited with {proc.returncode}"
        raise RuntimeError(msg)

    if not artifact_path.is_file():
        raise RuntimeError("live_runtime_result.json was not written")

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    stem_paths = payload.get("stem_paths") if isinstance(payload.get("stem_paths"), dict) else {}
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    device_used = str(meta.get("device_used") or device_flag)

    def rel(p: Path) -> str:
        return str(p.resolve().relative_to(root)).replace("\\", "/")

    def stem_key(key: str) -> str:
        raw = stem_paths.get(key) if isinstance(stem_paths, dict) else None
        if isinstance(raw, str) and raw.strip():
            return raw.strip().replace("\\", "/")
        return rel(output_dir / f"{key}.wav")

    return {
        "artifact_path": rel(artifact_path),
        "stem_urls": {
            "input": rel(input_media),
            "vocals": stem_key("vocals"),
            "drums": stem_key("drums"),
            "bass": stem_key("bass"),
            "other": stem_key("other"),
        },
        "timings": {
            "stft_ms": float(payload.get("stft_ms") or 0.0),
            "infer_ms": float(payload.get("infer_ms") or 0.0),
            "istft_ms": float(payload.get("istft_ms") or 0.0),
            "total_ms": float(payload.get("total_ms") or 0.0),
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
            result = _run_separation(
                mp3_bytes,
                device_str,
                Path(self.directory),
                file_item.filename,
            )
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
    parser.add_argument(
        "--benchmark",
        default=None,
        help="Optional benchmark / evidence JSON path to preload via ?benchmark= (must live inside the project root).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    directory = Path(args.directory).resolve()

    try:
        artifact = _encode_compare_artifact(args.artifact)
        artifact2 = _encode_compare_artifact(args.artifact2)
        benchmark = _encode_compare_artifact(args.benchmark) if args.benchmark else None
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
    compare_url = _build_compare_url(str(host), port, artifact, artifact2, benchmark)
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
