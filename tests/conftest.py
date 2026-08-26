from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain_foundry_core.clock import set_clock
from domain_foundry_core.paths import Workspace


def land_wizard(api, goal: str, reply: str = "skip", samples: list[str] | None = None):
    """Start a domain and accept the atlas pick so tests reach a live pack.

    An unindexed goal now asks for two sentences in the user's own words before
    it designs anything (ADR-010). ``samples`` answers them; the default answers
    "skip", which is the honest fallback to the pre-elicitation behaviour, so
    every existing caller keeps measuring exactly what it measured before.
    """
    turn = api.new_domain(goal)
    sid = turn.get("session_id")
    if turn.get("state") == "fork":
        turn = api.wizard_reply(sid, reply)
    if turn.get("state") == "looks":
        turn = api.wizard_reply(sid, "build it")
    pending = list(samples or [])
    while turn.get("state") == "elicit":
        turn = api.wizard_reply(sid, pending.pop(0) if pending else "skip")
    return turn


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
