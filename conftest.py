from __future__ import annotations

"""Pytest hooks for repo root — must live here so collection skips broken `.gsd` stubs before tests/conftest runs."""

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(collection_path, config):  # noqa: ARG001
    name = getattr(collection_path, "name", "")
    if name == ".gsd":
        return True
    try:
        if not collection_path.is_dir():
            return False
    except OSError:
        return True
    return False
