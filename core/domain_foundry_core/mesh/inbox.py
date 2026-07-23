"""Per-domain durable inbox queue (domain_inbox table)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from domain_foundry_core.clock import now_iso
from domain_foundry_core.ids import new_ulid
from domain_foundry_core.ledger.migrate import ensure_migrated
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_rw


@dataclass(frozen=True)
class InboxMessage:
    id: str
    domain: str
    journal_id: str
    payload: dict[str, Any]
    status: str
    enqueued_at: str
    claimed_at: str | None = None
    acked_at: str | None = None
    error: str | None = None
    reply: dict[str, Any] | None = None


class DomainInbox:
    """Durable work queue partitioned by domain."""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self.ws = workspace or Workspace()
        ensure_migrated(self.ws.ledger_db, "ledger")

    def _connect(self) -> sqlite3.Connection:
        return connect_rw(self.ws.ledger_db)

    def enqueue(
        self,
        domain: str,
        *,
        journal_id: str,
        payload: dict[str, Any],
    ) -> InboxMessage:
        """Insert a message onto a domain queue. Idempotent on (journal_id, domain)."""
        msg_id = new_ulid()
        ts = now_iso()
        payload_json = json.dumps(payload)
        conn = self._connect()
        try:
            existing = conn.execute(
                """
                SELECT * FROM domain_inbox
                WHERE journal_id = ? AND domain = ?
                """,
                (journal_id, domain),
            ).fetchone()
            if existing is not None:
                return self._row_to_msg(existing)

            conn.execute(
                """
                INSERT INTO domain_inbox (
                    id, domain, journal_id, payload_json, status, enqueued_at
                ) VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (msg_id, domain, journal_id, payload_json, ts),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM domain_inbox WHERE id = ?", (msg_id,)
            ).fetchone()
            return self._row_to_msg(row)
        finally:
            conn.close()

    def claim_next(self, domain: str) -> InboxMessage | None:
        """Atomically claim the oldest pending message for `domain`.

        Serial-within-domain: only one claim succeeds at a time per domain
        because the UPDATE filters on status='pending' and we process in order.
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM domain_inbox
                WHERE domain = ? AND status = 'pending'
                ORDER BY enqueued_at ASC, id ASC
                LIMIT 1
                """,
                (domain,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            ts = now_iso()
            conn.execute(
                """
                UPDATE domain_inbox
                SET status = 'processing', claimed_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (ts, row["id"]),
            )
            if conn.total_changes == 0:
                conn.commit()
                return None
            conn.commit()
            claimed = conn.execute(
                "SELECT * FROM domain_inbox WHERE id = ?", (row["id"],)
            ).fetchone()
            return self._row_to_msg(claimed)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ack(
        self,
        msg_id: str,
        *,
        reply: dict[str, Any] | None = None,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE domain_inbox
                SET status = 'done',
                    acked_at = ?,
                    reply_json = ?,
                    error = NULL
                WHERE id = ?
                """,
                (
                    now_iso(),
                    json.dumps(reply) if reply is not None else None,
                    msg_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def fail(self, msg_id: str, error: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE domain_inbox
                SET status = 'failed', acked_at = ?, error = ?
                WHERE id = ?
                """,
                (now_iso(), error, msg_id),
            )
            conn.commit()
        finally:
            conn.close()

    def depth(self, domain: str | None = None) -> dict[str, int]:
        conn = self._connect()
        try:
            if domain:
                rows = conn.execute(
                    """
                    SELECT status, COUNT(*) AS n FROM domain_inbox
                    WHERE domain = ? GROUP BY status
                    """,
                    (domain,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM domain_inbox GROUP BY status"
                ).fetchall()
            return {str(r["status"]): int(r["n"]) for r in rows}
        finally:
            conn.close()

    def depths_by_domain(self) -> dict[str, dict[str, int]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT domain, status, COUNT(*) AS n
                FROM domain_inbox
                GROUP BY domain, status
                """
            ).fetchall()
            out: dict[str, dict[str, int]] = {}
            for r in rows:
                out.setdefault(str(r["domain"]), {})[str(r["status"])] = int(r["n"])
            return out
        finally:
            conn.close()

    def get(self, msg_id: str) -> InboxMessage | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM domain_inbox WHERE id = ?", (msg_id,)
            ).fetchone()
            return self._row_to_msg(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def _row_to_msg(row: sqlite3.Row) -> InboxMessage:
        payload: dict[str, Any] = {}
        raw = row["payload_json"]
        if raw:
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    payload = loaded
            except json.JSONDecodeError:
                payload = {"raw": raw}
        reply = None
        if row["reply_json"]:
            try:
                reply = json.loads(row["reply_json"])
            except json.JSONDecodeError:
                reply = {"raw": row["reply_json"]}
        return InboxMessage(
            id=row["id"],
            domain=row["domain"],
            journal_id=row["journal_id"],
            payload=payload,
            status=row["status"],
            enqueued_at=row["enqueued_at"],
            claimed_at=row["claimed_at"],
            acked_at=row["acked_at"],
            error=row["error"],
            reply=reply,
        )
