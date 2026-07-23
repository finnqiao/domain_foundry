"""Durable domain_session store — multi-turn interactive state (mesh P2)."""

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

ACTIVE = "active"
COMPLETED = "completed"
CANCELLED = "cancelled"
PAUSED = "paused"


@dataclass(frozen=True)
class DomainSession:
    id: str
    domain: str
    user_id: str
    session_type: str
    state: dict[str, Any]
    status: str
    created_at: str
    updated_at: str


class DomainSessionStore:
    """CRUD for ``domain_session`` — Expert rehydrates mid-quiz from here."""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self.ws = workspace or Workspace()
        ensure_migrated(self.ws.ledger_db, "ledger")

    def _connect(self) -> sqlite3.Connection:
        return connect_rw(self.ws.ledger_db)

    def start(
        self,
        domain: str,
        session_type: str,
        *,
        user_id: str = "default",
        state: dict[str, Any] | None = None,
    ) -> DomainSession:
        sid = new_ulid()
        ts = now_iso()
        state_json = json.dumps(state or {}, separators=(",", ":"))
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO domain_session (
                    id, domain, user_id, session_type, state_json,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, domain, user_id, session_type, state_json, ACTIVE, ts, ts),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM domain_session WHERE id = ?", (sid,)
            ).fetchone()
            return self._row(row)
        finally:
            conn.close()

    def get(self, session_id: str) -> DomainSession | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM domain_session WHERE id = ?", (session_id,)
            ).fetchone()
            return self._row(row) if row else None
        finally:
            conn.close()

    def get_active(
        self,
        domain: str,
        *,
        user_id: str = "default",
        session_type: str | None = None,
    ) -> DomainSession | None:
        conn = self._connect()
        try:
            if session_type:
                row = conn.execute(
                    """
                    SELECT * FROM domain_session
                    WHERE domain = ? AND user_id = ? AND status = ?
                      AND session_type = ?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (domain, user_id, ACTIVE, session_type),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM domain_session
                    WHERE domain = ? AND user_id = ? AND status = ?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (domain, user_id, ACTIVE),
                ).fetchone()
            return self._row(row) if row else None
        finally:
            conn.close()

    def save_state(self, session_id: str, state: dict[str, Any]) -> DomainSession:
        ts = now_iso()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE domain_session
                SET state_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(state, separators=(",", ":")), ts, session_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM domain_session WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"domain_session not found: {session_id}")
            return self._row(row)
        finally:
            conn.close()

    def complete(self, session_id: str, *, status: str = COMPLETED) -> DomainSession:
        if status not in {COMPLETED, CANCELLED, PAUSED}:
            raise ValueError(f"invalid terminal status {status!r}")
        ts = now_iso()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE domain_session
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, ts, session_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM domain_session WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"domain_session not found: {session_id}")
            return self._row(row)
        finally:
            conn.close()

    @staticmethod
    def _row(row: sqlite3.Row) -> DomainSession:
        state = json.loads(row["state_json"] or "{}")
        if not isinstance(state, dict):
            state = {}
        return DomainSession(
            id=row["id"],
            domain=row["domain"],
            user_id=row["user_id"],
            session_type=row["session_type"],
            state=state,
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
