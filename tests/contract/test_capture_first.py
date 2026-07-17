from __future__ import annotations

import sqlite3

from domain_foundry_core.ledger.capture import CaptureService
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro


def _counts(conn: sqlite3.Connection) -> tuple[int, int]:
    ce = conn.execute("SELECT COUNT(*) FROM capture_event").fetchone()[0]
    en = conn.execute("SELECT COUNT(*) FROM entry").fetchone()[0]
    return int(ce), int(en)


def test_capture_first_ordering_observable(workspace: Workspace):
    svc = CaptureService(workspace)
    receipt = svc.capture("synthetic loaf notes for contract test", channel="cli")

    assert receipt.status == "ledger_only"
    assert receipt.entry_id
    assert receipt.capture_event_id
    assert receipt.idempotent_replay is False

    conn = connect_ro(workspace.ledger_db)
    try:
        ce, en = _counts(conn)
        assert ce == 1 and en == 1
        row = conn.execute(
            """
            SELECT c.id AS capture_id, c.raw_text, e.id AS entry_id, e.capture_event_id,
                   e.status, e.fallback_tier
            FROM capture_event c
            JOIN entry e ON e.capture_event_id = c.id
            """
        ).fetchone()
        assert row["capture_id"] == receipt.capture_event_id
        assert row["entry_id"] == receipt.entry_id
        assert row["raw_text"].startswith("synthetic loaf")
        assert row["status"] == "ledger_only"
        assert row["fallback_tier"] == "ledger_only"
        # source_link present
        link = conn.execute(
            "SELECT * FROM source_link WHERE source_id = ? AND target_id = ?",
            (receipt.capture_event_id, receipt.entry_id),
        ).fetchone()
        assert link is not None
    finally:
        conn.close()


def test_idempotent_double_capture(workspace: Workspace):
    svc = CaptureService(workspace)
    r1 = svc.capture("same message twice", channel="telegram", source_ref="msg-42")
    r2 = svc.capture("same message twice (ignored body)", channel="telegram", source_ref="msg-42")

    assert r2.idempotent_replay is True
    assert r2.entry_id == r1.entry_id
    assert r2.capture_event_id == r1.capture_event_id

    conn = connect_ro(workspace.ledger_db)
    try:
        ce, en = _counts(conn)
        assert ce == 1 and en == 1
    finally:
        conn.close()


def test_receipt_complete_fields(workspace: Workspace):
    svc = CaptureService(workspace)
    r = svc.capture("complete receipt check", channel="web", source_ref="web-1")
    payload = r.model_dump()
    for key in (
        "entry_id",
        "capture_event_id",
        "status",
        "routed",
        "projection_status",
        "idempotent_replay",
    ):
        assert key in payload
    assert isinstance(payload["routed"], list) and payload["routed"]


def test_secrets_redacted_before_persist(workspace: Workspace):
    svc = CaptureService(workspace)
    r = svc.capture(
        "token sk-abcdefghijklmnopqrstuvwxyz012345 and note",
        channel="cli",
    )
    conn = connect_ro(workspace.ledger_db)
    try:
        text = conn.execute(
            "SELECT raw_text FROM capture_event WHERE id = ?",
            (r.capture_event_id,),
        ).fetchone()["raw_text"]
    finally:
        conn.close()
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in text
    assert "[REDACTED]" in text


def test_health_fk_and_integrity_clean(workspace: Workspace):
    svc = CaptureService(workspace)
    svc.capture("health probe", channel="cli")
    report = svc.health()
    assert report.ok is True
    assert report.ledger.ok is True
    assert report.domains.ok is True
    assert report.ledger.schema_version >= 1
    assert report.entry_counts.get("ledger_only", 0) >= 1
    assert report.last_capture_at is not None


def test_query_and_fts(workspace: Workspace):
    svc = CaptureService(workspace)
    svc.capture("watered the monstera yesterday", channel="cli")
    svc.capture("unrelated grocery list", channel="cli")
    rows = svc.query(q="monstera")
    assert len(rows) == 1
    assert "monstera" in (rows[0].raw_text or "")
    by_status = svc.query(status="ledger_only")
    assert len(by_status) == 2
