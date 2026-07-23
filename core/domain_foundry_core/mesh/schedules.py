"""Schedule run bookkeeping (mesh P2).

Outbound delivery lives in ``mesh.outbound`` (ledger_006). This module only
tracks idempotent last-fired / next-due per ``(domain, schedule_id)``.
"""

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
class ScheduleRun:
    id: str
    domain: str
    schedule_id: str
    last_fired_at: str | None
    next_due_at: str | None
    fire_count: int
    last_result: dict[str, Any] | None
    created_at: str
    updated_at: str


class ScheduleRunStore:
    """Idempotent last-fired / next-due per ``(domain, schedule_id)``."""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self.ws = workspace or Workspace()
        ensure_migrated(self.ws.ledger_db, "ledger")

    def _connect(self) -> sqlite3.Connection:
        return connect_rw(self.ws.ledger_db)

    def get(self, domain: str, schedule_id: str) -> ScheduleRun | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM schedule_run
                WHERE domain = ? AND schedule_id = ?
                """,
                (domain, schedule_id),
            ).fetchone()
            return self._row(row) if row else None
        finally:
            conn.close()

    def ensure(
        self, domain: str, schedule_id: str, *, next_due_at: str | None = None
    ) -> ScheduleRun:
        existing = self.get(domain, schedule_id)
        if existing is not None:
            return existing
        rid = new_ulid()
        ts = now_iso()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO schedule_run (
                    id, domain, schedule_id, last_fired_at, next_due_at,
                    fire_count, last_result_json, created_at, updated_at
                ) VALUES (?, ?, ?, NULL, ?, 0, NULL, ?, ?)
                """,
                (rid, domain, schedule_id, next_due_at, ts, ts),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM schedule_run WHERE id = ?", (rid,)
            ).fetchone()
            return self._row(row)
        finally:
            conn.close()

    def record_fire(
        self,
        domain: str,
        schedule_id: str,
        *,
        next_due_at: str | None,
        result: dict[str, Any] | None = None,
    ) -> ScheduleRun:
        """Mark a schedule as fired. Safe to call once per window (caller gates)."""
        self.ensure(domain, schedule_id)
        ts = now_iso()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE schedule_run
                SET last_fired_at = ?,
                    next_due_at = ?,
                    fire_count = fire_count + 1,
                    last_result_json = ?,
                    updated_at = ?
                WHERE domain = ? AND schedule_id = ?
                """,
                (
                    ts,
                    next_due_at,
                    json.dumps(result, separators=(",", ":")) if result is not None else None,
                    ts,
                    domain,
                    schedule_id,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT * FROM schedule_run
                WHERE domain = ? AND schedule_id = ?
                """,
                (domain, schedule_id),
            ).fetchone()
            return self._row(row)
        finally:
            conn.close()

    @staticmethod
    def _row(row: sqlite3.Row) -> ScheduleRun:
        result = None
        if row["last_result_json"]:
            parsed = json.loads(row["last_result_json"])
            if isinstance(parsed, dict):
                result = parsed
        return ScheduleRun(
            id=row["id"],
            domain=row["domain"],
            schedule_id=row["schedule_id"],
            last_fired_at=row["last_fired_at"],
            next_due_at=row["next_due_at"],
            fire_count=int(row["fire_count"] or 0),
            last_result=result,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
