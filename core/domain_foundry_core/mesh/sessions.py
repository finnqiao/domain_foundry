"""Durable domain_session store — multi-turn interactive state (mesh P2/P3)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from domain_foundry_core.clock import now, now_iso
from domain_foundry_core.ids import new_ulid
from domain_foundry_core.ledger.migrate import ensure_migrated
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_rw

ACTIVE = "active"
COMPLETED = "completed"
CANCELLED = "cancelled"
PAUSED = "paused"

STICKY_SESSION_TYPE = "sticky"


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
    """CRUD for ``domain_session`` — Expert rehydrates; Concierge reads sticky."""

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

    def list(
        self,
        domain: str,
        *,
        user_id: str = "default",
        session_type: str | None = None,
        limit: int = 20,
    ) -> list[DomainSession]:
        """Return recent sessions for a visible activity/history surface."""
        conn = self._connect()
        try:
            params: list[Any] = [domain, user_id]
            sql = """
                SELECT * FROM domain_session
                WHERE domain = ? AND user_id = ?
            """
            if session_type:
                sql += " AND session_type = ?"
                params.append(session_type)
            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(max(1, min(int(limit), 100)))
            return [self._row(row) for row in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def get_sticky(
        self,
        *,
        user_id: str = "default",
        ttl_s: float = 900.0,
    ) -> DomainSession | None:
        """Most recently updated active session for user within TTL."""
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM domain_session
                WHERE user_id = ? AND status = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (user_id, ACTIVE),
            ).fetchone()
            if row is None:
                return None
            session = self._row(row)
            if not self._within_ttl(session.updated_at, ttl_s):
                return None
            return session
        finally:
            conn.close()

    def touch(self, session_id: str) -> DomainSession:
        """Bump updated_at so stickiness TTL renews on activity."""
        ts = now_iso()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE domain_session SET updated_at = ? WHERE id = ?",
                (ts, session_id),
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

    def pause_active_for_user(self, *, user_id: str = "default") -> int:
        """Pause all active sessions for a user (switch command)."""
        ts = now_iso()
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                UPDATE domain_session
                SET status = ?, updated_at = ?
                WHERE user_id = ? AND status = ?
                """,
                (PAUSED, ts, user_id, ACTIVE),
            )
            conn.commit()
            return int(cur.rowcount)
        finally:
            conn.close()

    def force_sticky(
        self,
        domain: str,
        *,
        user_id: str = "default",
        session_type: str = STICKY_SESSION_TYPE,
        pause_others: bool = True,
    ) -> DomainSession:
        """Force sticky domain: pause others, start/touch a session on domain."""
        if pause_others:
            self.pause_active_for_user(user_id=user_id)
        existing = self.get_active(domain, user_id=user_id, session_type=session_type)
        if existing is not None:
            # Reactivate if somehow paused mid-race (shouldn't after pause_others).
            if existing.status != ACTIVE:
                return self._reactivate(existing.id)
            return self.touch(existing.id)
        return self.start(domain, session_type, user_id=user_id, state={"source": "switch"})

    def _reactivate(self, session_id: str) -> DomainSession:
        ts = now_iso()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE domain_session
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (ACTIVE, ts, session_id),
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
    def _within_ttl(updated_at: str, ttl_s: float) -> bool:
        if ttl_s <= 0:
            return True
        try:
            # ISO with Z → aware datetime
            ts = updated_at.replace("Z", "+00:00")
            from datetime import datetime

            updated = datetime.fromisoformat(ts)
        except ValueError:
            return False
        return now() - updated <= timedelta(seconds=ttl_s)

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
