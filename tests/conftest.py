from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain_foundry_core.clock import set_clock
from domain_foundry_core.paths import Workspace


@pytest.fixture
def frozen_clock():
    fixed = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)
    set_clock(lambda: fixed)
    yield fixed
    set_clock(None)


@pytest.fixture
def workspace(tmp_path: Path, frozen_clock, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    home = tmp_path / "home"
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(home))
    monkeypatch.delenv("DOMAIN_FOUNDRY_PACKS_PATH", raising=False)
    monkeypatch.delenv("DOMAIN_FOUNDRY_PACKS", raising=False)
    ws = Workspace(home)
    ws.ensure_layout()
    return ws
