"""Shared fixtures for the release-proof gates.

These gates are run on purpose, not by accident. Several of them are red while
the rebuild lanes land, and a red rebuild gate must not break the standing test
suite or the standing release audit. So a bare `pytest` skips this directory,
and you get it by naming the path:

    python -m pytest tests/e2e-foundry -q

`scripts/release_audit.sh --rebuild-gates` runs them for you.

When all four gates are green, delete `pytest_ignore_collect` below and add this
directory to `testpaths` in `pyproject.toml`, so a plain `pytest` runs them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CASSETTE_ROOT = Path(__file__).resolve().parent / "cassettes"

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def cassette_root() -> Path:
    return CASSETTE_ROOT


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Collect these gates only when someone asks for them by path."""
    asked = any("e2e-foundry" in str(argument) for argument in config.args)
    return None if asked else True
