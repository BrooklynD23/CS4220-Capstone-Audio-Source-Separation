from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ui.encode_artifact_path import encode_artifact_path


def test_simple_relative_path(tmp_path):
    artifact = tmp_path / "artifacts" / "live" / "result.json"
    artifact.parent.mkdir(parents=True)
    artifact.touch()
    result = encode_artifact_path(str(tmp_path), str(artifact))
    assert result == "/artifacts/live/result.json"


def test_path_with_spaces(tmp_path):
    sub = tmp_path / "live results"
    sub.mkdir()
    artifact = sub / "data.json"
    artifact.touch()
    result = encode_artifact_path(str(tmp_path), str(artifact))
    assert result == "/live%20results/data.json"


def test_outside_repo_raises(tmp_path):
    other = tmp_path.parent / "other_dir_encode_test"
    with pytest.raises(ValueError):
        encode_artifact_path(str(tmp_path), str(other / "result.json"))


def test_starts_with_slash(tmp_path):
    artifact = tmp_path / "foo.json"
    artifact.touch()
    result = encode_artifact_path(str(tmp_path), str(artifact))
    assert result.startswith("/")
