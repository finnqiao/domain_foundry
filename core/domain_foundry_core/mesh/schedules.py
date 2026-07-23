"""Schedule run bookkeeping + cron evaluator (mesh P2 Anki parity).

Outbound delivery lives in ``mesh.outbound`` (ledger_006). This module tracks
idempotent last-fired / next-due per ``(domain, schedule_id)`` and evaluates
pack ``agent.yaml`` schedules (daily 09:00 quiz nudge).
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from domain_foundry_core.clock import now, now_iso
from domain_foundry_core.ids import new_ulid
from domain_foundry_core.ledger.migrate import ensure_migrated
from domain_foundry_core.packs.models import AgentScheduleSpec, DomainPack
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.packs.schema_compiler import table_name
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro, connect_rw

# Minimal cron: "M H * * *" (minute hour, daily).
_CRON_DAILY_RE = re.compile(
    r"^\s*(?P<minute>\d{1,2})\s+(?P<hour>\d{1,2})\s+\*\s+\*\s+\*\s*$"
)


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


@dataclass(frozen=True)
class CronWindow:
    """One firing window for a simple daily cron."""

    minute: int
    hour: int
    window_start: datetime
    next_window_start: datetime

    @property
    def window_id(self) -> str:
        return _as_utc(self.window_start).strftime("%Y-%m-%dT%H:%M")


@dataclass(frozen=True)
class ScheduleFireResult:
    domain: str
    schedule_id: str
    fired: bool
    skipped_reason: str | None
    window_id: str | None
    next_due_at: str | None
    result: dict[str, Any] | None = None


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _iso(dt: datetime) -> str:
    return _as_utc(dt).isoformat().replace("+00:00", "Z")


def parse_daily_cron(cron: str) -> tuple[int, int]:
    """Return (minute, hour) for ``M H * * *`` crons."""
    m = _CRON_DAILY_RE.match(cron or "")
    if not m:
        raise ValueError(f"unsupported cron {cron!r}; expected 'M H * * *'")
    minute = int(m.group("minute"))
    hour = int(m.group("hour"))
    if not (0 <= minute <= 59 and 0 <= hour <= 23):
        raise ValueError(f"cron out of range: {cron!r}")
    return minute, hour


def cron_window_for(cron: str, at: datetime) -> CronWindow:
    """Daily window containing ``at`` (or the most recent past 09:00-style slot)."""
    minute, hour = parse_daily_cron(cron)
    now_utc = _as_utc(at)
    today_start = now_utc.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now_utc < today_start:
        window_start = today_start - timedelta(days=1)
    else:
        window_start = today_start
    next_start = window_start + timedelta(days=1)
    return CronWindow(
        minute=minute,
        hour=hour,
        window_start=window_start,
        next_window_start=next_start,
    )


def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    raw = str(ts).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    return _as_utc(dt)


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

    def already_fired_in_window(self, domain: str, schedule_id: str, window: CronWindow) -> bool:
        run = self.get(domain, schedule_id)
        if run is None or not run.last_fired_at:
            return False
        last = parse_iso(run.last_fired_at)
        if last is None:
            return False
        return last >= window.window_start

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


class ScheduleEvaluator:
    """Evaluate pack schedules; fire at most once per cron window via schedule_run."""

    def __init__(
        self,
        workspace: Workspace | None = None,
        *,
        registry: PackRegistry | None = None,
    ) -> None:
        self.ws = workspace or Workspace()
        self.registry = registry or PackRegistry(self.ws)
        self.store = ScheduleRunStore(self.ws)

    def evaluate_domain(
        self,
        domain: str,
        *,
        at: datetime | None = None,
        fire: bool = True,
        user_id: str = "default",
        channel: str = "telegram",
    ) -> list[ScheduleFireResult]:
        pack = self.registry.get(domain)
        if pack is None or pack.agent is None:
            return []
        when = at or now()
        out: list[ScheduleFireResult] = []
        for spec in pack.agent.schedules:
            out.append(
                self._evaluate_one(
                    pack,
                    spec,
                    at=when,
                    fire=fire,
                    user_id=user_id,
                    channel=channel,
                )
            )
        return out

    def evaluate_all(
        self,
        *,
        at: datetime | None = None,
        fire: bool = True,
        domains: list[str] | None = None,
    ) -> list[ScheduleFireResult]:
        results: list[ScheduleFireResult] = []
        for pack in self.registry.list():
            if domains is not None and pack.name not in domains:
                continue
            if pack.agent is None or not pack.agent.schedules:
                continue
            results.extend(
                self.evaluate_domain(pack.name, at=at, fire=fire)
            )
        return results

    def _evaluate_one(
        self,
        pack: DomainPack,
        spec: AgentScheduleSpec,
        *,
        at: datetime,
        fire: bool,
        user_id: str,
        channel: str,
    ) -> ScheduleFireResult:
        domain = pack.name
        try:
            window = cron_window_for(spec.cron, at)
        except ValueError as exc:
            return ScheduleFireResult(
                domain=domain,
                schedule_id=spec.id,
                fired=False,
                skipped_reason=str(exc),
                window_id=None,
                next_due_at=None,
            )

        next_due = _iso(window.next_window_start)
        # Ensure a row exists so operators can inspect next_due even before first fire.
        self.store.ensure(domain, spec.id, next_due_at=next_due)

        if _as_utc(at) < window.window_start:
            return ScheduleFireResult(
                domain=domain,
                schedule_id=spec.id,
                fired=False,
                skipped_reason="before_window",
                window_id=window.window_id,
                next_due_at=next_due,
            )

        if self.store.already_fired_in_window(domain, spec.id, window):
            return ScheduleFireResult(
                domain=domain,
                schedule_id=spec.id,
                fired=False,
                skipped_reason="already_fired",
                window_id=window.window_id,
                next_due_at=next_due,
            )

        due_count = self._when_count(pack, spec)
        if due_count is not None and due_count <= 0:
            # Still mark the window so we don't re-check every poll; no outbound.
            if fire:
                self.store.record_fire(
                    domain,
                    spec.id,
                    next_due_at=next_due,
                    result={"skipped": "when_empty", "count": 0, "window_id": window.window_id},
                )
            return ScheduleFireResult(
                domain=domain,
                schedule_id=spec.id,
                fired=False,
                skipped_reason="when_empty",
                window_id=window.window_id,
                next_due_at=next_due,
                result={"count": 0},
            )

        if not fire:
            return ScheduleFireResult(
                domain=domain,
                schedule_id=spec.id,
                fired=False,
                skipped_reason="dry_run",
                window_id=window.window_id,
                next_due_at=next_due,
                result={"count": due_count},
            )

        action_result = self._fire_action(
            pack,
            spec,
            due_count=due_count,
            user_id=user_id,
            channel=channel,
            window=window,
            next_due_at=next_due,
        )
        return ScheduleFireResult(
            domain=domain,
            schedule_id=spec.id,
            fired=True,
            skipped_reason=None,
            window_id=window.window_id,
            next_due_at=next_due,
            result=action_result,
        )

    def _when_count(self, pack: DomainPack, spec: AgentScheduleSpec) -> int | None:
        """Run a restricted COUNT when-clause, or None if absent."""
        from domain_foundry_core.clock import today_utc

        sql = (spec.when or "").strip()
        if not sql:
            return None
        # Only allow SELECT count(*) FROM <domain__table> ... patterns we emit.
        if not sql.upper().startswith("SELECT"):
            return None
        # Safety: table must belong to this pack.
        expected_prefix = f"{pack.name}__"
        if expected_prefix not in sql:
            return None
        if not self.ws.domains_db.exists():
            return 0
        # Prefer injectable clock over SQLite date('now').
        day = today_utc()
        safe_sql = sql.replace("date('now')", "?").replace('date("now")', "?")
        params: tuple[Any, ...] = ()
        if "?" in safe_sql and "date(" in sql.lower():
            params = tuple(day for _ in range(safe_sql.count("?")))
        conn = connect_ro(self.ws.domains_db)
        try:
            row = conn.execute(safe_sql, params).fetchone()
            if row is None:
                return 0
            return int(row[0] or 0)
        except Exception:
            return 0
        finally:
            conn.close()

    def _fire_action(
        self,
        pack: DomainPack,
        spec: AgentScheduleSpec,
        *,
        due_count: int | None,
        user_id: str,
        channel: str,
        window: CronWindow,
        next_due_at: str,
    ) -> dict[str, Any]:
        from domain_foundry_core.mesh.outbound import OutboundQueue
        from domain_foundry_core.mesh.quiz import QuizSession

        count = int(due_count or 0)
        session_id = None
        outbound_id = None

        if "start_session" in (spec.action or "") and pack.name == "japanese":
            quiz = QuizSession(self.ws, registry=self.registry)
            # start_from_schedule records fire itself — use a lower-level path
            # so the evaluator owns idempotency.
            session = quiz.start(user_id=user_id)
            session_id = session.id
            count = len(session.state.get("cards") or [])
            message = (spec.message or "You have {count} Japanese cards due. Want to review now?").format(
                count=count
            )
            outbound = OutboundQueue(self.ws).enqueue(
                origin_domain=pack.name,
                text=message,
                channel=channel,
                destination=user_id,
                payload={
                    "schedule_id": spec.id,
                    "session_id": session.id,
                    "count": count,
                    "window_id": window.window_id,
                },
            )
            outbound_id = outbound.id
        else:
            message = (spec.message or "Schedule fired.").format(count=count)
            outbound = OutboundQueue(self.ws).enqueue(
                origin_domain=pack.name,
                text=message,
                channel=channel,
                destination=user_id,
                payload={"schedule_id": spec.id, "count": count, "window_id": window.window_id},
            )
            outbound_id = outbound.id

        result = {
            "session_id": session_id,
            "outbound_id": outbound_id,
            "count": count,
            "window_id": window.window_id,
        }
        self.store.record_fire(
            pack.name, spec.id, next_due_at=next_due_at, result=result
        )
        return result


def due_vocab_count(workspace: Workspace, *, as_of: str | None = None) -> int:
    """Count jp_vocab rows with next_review <= as_of (UTC date)."""
    from domain_foundry_core.clock import today_utc

    day = as_of or today_utc()
    tname = table_name("japanese", "jp_vocab")
    if not workspace.domains_db.exists():
        return 0
    conn = connect_ro(workspace.domains_db)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (tname,),
        ).fetchone()
        if not exists:
            return 0
        row = conn.execute(
            f"""
            SELECT count(*) FROM {tname}
            WHERE tombstoned = 0
              AND next_review IS NOT NULL
              AND next_review <= ?
            """,
            (day,),
        ).fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()
