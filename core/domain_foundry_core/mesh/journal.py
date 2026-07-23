"""Append-only inbox_journal client — transport-level capture-first."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from domain_foundry_core.clock import now_iso
from domain_foundry_core.ids import new_ulid
from domain_foundry_core.ledger.migrate import ensure_migrated
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_rw


@dataclass(frozen=True)
class JournalRecord:
    id: str
    channel: str
    source_ref: str | None
    actor: str | None
    raw_text: str
    payload: dict[str, Any] | None
    status: str
    routed_domain: str | None
    domain_inbox_id: str | None
    journaled_at: str
    routed_at: str | None
    idempotent_replay: bool = False


class InboxJournal:
    """Durable append-only journal. Message is safe once append() returns."""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self.ws = workspace or Workspace()
        ensure_migrated(self.ws.ledger_db, "ledger")

    def _connect(self) -> sqlite3.Connection:
        return connect_rw(self.ws.ledger_db)

    def append(
        self,
        text: str,
        *,
        channel: str = "cli",
        source_ref: str | None = None,
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> JournalRecord:
        """Journal an inbound message before any routing/processing.

        Idempotent on (channel, source_ref) when source_ref is set.
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("raw_text must be non-empty")

        journal_id = new_ulid()
        ts = now_iso()
        payload_json = json.dumps(payload) if payload is not None else None

        conn = self._connect()
        try:
            if source_ref:
                existing = conn.execute(
                    "SELECT * FROM inbox_journal WHERE channel = ? AND source_ref = ?",
                    (channel, source_ref),
                ).fetchone()
                if existing is not None:
                    return self._row_to_record(existing, idempotent_replay=True)

            conn.execute(
                """
                INSERT INTO inbox_journal (
                    id, channel, source_ref, actor, raw_text, payload_json,
                    status, journaled_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (journal_id, channel, source_ref, actor, text, payload_json, ts),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM inbox_journal WHERE id = ?", (journal_id,)
            ).fetchone()
            return self._row_to_record(row, idempotent_replay=False)
        finally:
            conn.close()

    def get(self, journal_id: str) -> JournalRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM inbox_journal WHERE id = ?", (journal_id,)
            ).fetchone()
            return self._row_to_record(row) if row else None
        finally:
            conn.close()

    def list_pending(self, *, limit: int = 100) -> list[JournalRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM inbox_journal
                WHERE status = 'pending'
                ORDER BY journaled_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._row_to_record(r) for r in rows]
        finally:
            conn.close()

    def mark_routed(
        self,
        journal_id: str,
        *,
        domain: str,
        domain_inbox_id: str,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE inbox_journal
                SET status = 'routed',
                    routed_domain = ?,
                    domain_inbox_id = ?,
                    routed_at = ?,
                    error = NULL
                WHERE id = ?
                """,
                (domain, domain_inbox_id, now_iso(), journal_id),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_failed(self, journal_id: str, error: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE inbox_journal
                SET status = 'failed', error = ?, routed_at = ?
                WHERE id = ?
                """,
                (error, now_iso(), journal_id),
            )
            conn.commit()
        finally:
            conn.close()

    def counts(self) -> dict[str, int]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM inbox_journal GROUP BY status"
            ).fetchall()
            return {str(r["status"]): int(r["n"]) for r in rows}
        finally:
            conn.close()

    @staticmethod
    def _row_to_record(
        row: sqlite3.Row, *, idempotent_replay: bool = False
    ) -> JournalRecord:
        payload = None
        raw_payload = row["payload_json"]
        if raw_payload:
            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError:
                payload = {"raw": raw_payload}
        return JournalRecord(
            id=row["id"],
            channel=row["channel"],
            source_ref=row["source_ref"],
            actor=row["actor"],
            raw_text=row["raw_text"],
            payload=payload,
            status=row["status"],
            routed_domain=row["routed_domain"],
            domain_inbox_id=row["domain_inbox_id"],
            journaled_at=row["journaled_at"],
            routed_at=row["routed_at"],
            idempotent_replay=idempotent_replay,
        )


def ensure_mesh_schema(ledger_db: Path) -> int:
    """Apply ledger migrations (includes mesh tables). Returns schema version."""
    return ensure_migrated(ledger_db, "ledger")
