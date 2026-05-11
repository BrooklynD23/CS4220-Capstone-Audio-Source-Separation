"""URL-encode an artifact path relative to a repo root for use in batch files.

Usage:
    python encode_artifact_path.py <repo-root> <artifact-path>

Prints the URL-encoded path (e.g. /artifacts/live/result.json) to stdout.
Exits 1 if the artifact is outside the repo root.
Exits 2 on wrong number of arguments.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote


def encode_artifact_path(root: str, artifact: str) -> str:
    """Return '/' + URL-encoded posix relative path from root to artifact.

    Raises ValueError if artifact is not inside root.
    """
    root_path = Path(root).resolve()
    artifact_path = Path(artifact).resolve()
    relative = artifact_path.relative_to(root_path)
    return "/" + quote(relative.as_posix(), safe="/")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <repo-root> <artifact-path>", file=sys.stderr)
        sys.exit(2)
    try:
        print(encode_artifact_path(sys.argv[1], sys.argv[2]))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
