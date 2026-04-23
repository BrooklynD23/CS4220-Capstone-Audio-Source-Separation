from __future__ import annotations

import argparse
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIRECTORY = PROJECT_ROOT
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8000


class CompareDemoHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003 - stdlib API
        message = format % args
        print(f"compare-demo: {self.client_address[0]} {message}", file=sys.stderr)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the compare UI from a local static root.")
    parser.add_argument(
        "--bind",
        default=DEFAULT_BIND,
        help=f"Interface to bind to (default: {DEFAULT_BIND})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--directory",
        default=str(DEFAULT_DIRECTORY),
        help="Directory to serve (default: repository root)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    directory = Path(args.directory).resolve()

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
    print(f"compare-demo: serving {directory} at http://{host}:{port}/ui/compare/", flush=True)

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
