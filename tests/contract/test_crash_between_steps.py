from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from domain_expert_core.ids import new_ulid
from domain_expert_core.ledger import capture as capture_mod
from domain_expert_core.ledger.capture import CaptureService
from domain_expert_core.paths import Workspace
from domain_expert_core.security.redact import redact_secrets
from domain_expert_core.security.store import connect_rw, integrity_check


class _FlakyConn:
    """Wraps a real connection; fails once on INSERT INTO entry."""

    def __init__(self, inner: sqlite3.Connection, state: dict[str, int]) -> None:
        self._inner = inner
        self._state = state

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        if isinstance(sql, str) and "INSERT INTO entry (" in sql:
            self._state["entry_inserts"] += 1
            if self._state["entry_inserts"] == 1:
                raise sqlite3.OperationalError("simulated crash after capture_event")
        return self._inner.execute(sql, parameters)

    def commit(self) -> None:
        self._inner.commit()

    def close(self) -> None:
        self._inner.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def test_ledger_anchor_survives_partial_failure(workspace: Workspace, monkeypatch):
    """
    Single-transaction capture: a crash mid-insert rolls back fully.
    Store stays FK-clean; retry with same source_ref succeeds once.
    """
    svc = CaptureService(workspace)
    state = {"entry_inserts": 0}
    real_connect = capture_mod.connect_rw

    def flaky_connect(path):  # type: ignore[no-untyped-def]
        return _FlakyConn(real_connect(path), state)

    monkeypatch.setattr(capture_mod, "connect_rw", flaky_connect)

    with pytest.raises(sqlite3.OperationalError):
        svc.capture("crash injection capture", channel="cli", source_ref="crash-1")

    health = integrity_check(workspace.ledger_db)
    assert health["ok"] is True

    # Restore real connect for the successful retry
    monkeypatch.setattr(capture_mod, "connect_rw", real_connect)
    receipt = svc.capture("crash injection capture", channel="cli", source_ref="crash-1")
    assert receipt.status == "ledger_only"
    assert receipt.idempotent_replay is False

    conn = connect_rw(workspace.ledger_db)
    try:
        ce = conn.execute("SELECT COUNT(*) FROM capture_event").fetchone()[0]
        en = conn.execute("SELECT COUNT(*) FROM entry").fetchone()[0]
        assert ce == 1 and en == 1
        orphans = conn.execute(
            """
            SELECT e.id FROM entry e
            LEFT JOIN capture_event c ON c.id = e.capture_event_id
            WHERE c.id IS NULL
            """
        ).fetchall()
        assert orphans == []
    finally:
        conn.close()


def test_ulid_helpers_stable_shape():
    uid = new_ulid()
    assert len(uid) == 26
    assert redact_secrets("ok") == "ok"
