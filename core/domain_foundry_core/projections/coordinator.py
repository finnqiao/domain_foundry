"""ProjectionCoordinator — durable outbox drain with per-adapter watermarks.

Canonical commits enqueue rows in `projection_outbox` (invariant 11). The
coordinator drains them *outside* the canonical transaction so a rendering or
IO failure never rolls back capture (invariant 4). Failed rows stay `pending`
and are retried from durable state on the next drain / daemon restart.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from domain_foundry_core.clock import now, now_iso
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro, connect_rw

if TYPE_CHECKING:
    import sqlite3

# Adapters that a canonical commit fans out to. Direct-query block data, the
# managed markdown vault, and the food venues GeoJSON artifact.
DEFAULT_ADAPTERS: tuple[str, ...] = ("app_feed", "markdown", "geojson")

_TERMINAL_STATUS = frozenset({"done"})
_RETRYABLE_STATUS = frozenset({"pending", "failed", "draining"})


class ProjectionAdapter(Protocol):
    """A projection target. `render` must be idempotent and side-effect scoped."""

    name: str

    def render(self, object_key: str, outbox_row: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass
class DrainReport:
    drained: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)

    @property
    def drained_count(self) -> int:
        return len(self.drained)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "drained": self.drained,
            "failed": self.failed,
            "drained_count": self.drained_count,
            "failed_count": self.failed_count,
        }


class ProjectionCoordinator:
    """Owns the outbox → adapter drain loop and per-adapter watermarks."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        registry: PackRegistry | None = None,
        adapters: dict[str, ProjectionAdapter] | None = None,
    ) -> None:
        self.ws = workspace
        self.registry = registry or PackRegistry(workspace)
        if adapters is None:
            adapters = self._default_adapters()
        self.adapters: dict[str, ProjectionAdapter] = adapters

    def _default_adapters(self) -> dict[str, ProjectionAdapter]:
        # Imported lazily to avoid a circular import at module load.
        from domain_foundry_core.projections.blockdata import BlockDataAdapter
        from domain_foundry_core.projections.geojson import GeoJsonAdapter
        from domain_foundry_core.projections.markdown import MarkdownAdapter

        return {
            "app_feed": BlockDataAdapter(self.ws, registry=self.registry),
            "markdown": MarkdownAdapter(self.ws, registry=self.registry),
            "geojson": GeoJsonAdapter(self.ws, registry=self.registry),
        }

    def register(self, adapter: ProjectionAdapter) -> None:
        self.adapters[adapter.name] = adapter

    # ------------------------------------------------------------------ enqueue
    def mark_dirty(
        self,
        *,
        adapter: str,
        object_key: str = "default",
        reason: str | None = None,
        change_request_id: int | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """Record that `adapter`/`object_key` must converge to canonical state.

        Coalesces onto an existing pending row for the same (adapter, object_key)
        so a burst of commits does not create redundant work.
        """
        owns = conn is None
        c = conn or connect_rw(self.ws.ledger_db)
        try:
            return enqueue_projection(
                c,
                adapter=adapter,
                object_key=object_key,
                reason=reason,
                change_request_id=change_request_id,
                now=now_iso(),
            )
        finally:
            if owns:
                c.commit()
                c.close()

    # -------------------------------------------------------------------- drain
    def drain(
        self,
        *,
        adapters: Iterable[str] | None = None,
        limit: int = 50,
    ) -> DrainReport:
        """Process pending outbox rows. Failures stay pending for retry."""
        wanted = set(adapters) if adapters is not None else set(self.adapters)
        report = DrainReport()
        conn = connect_rw(self.ws.ledger_db)
        try:
            placeholders = ",".join("?" for _ in wanted) or "''"
            pending = conn.execute(
                f"""
                SELECT id, adapter, object_key, reason, change_request_id, attempts
                FROM projection_outbox
                WHERE status IN ('pending', 'failed')
                  AND adapter IN ({placeholders})
                ORDER BY id ASC
                LIMIT ?
                """,
                (*sorted(wanted), int(limit)),
            ).fetchall()

            for row in pending:
                outbox_id = int(row["id"])
                adapter_name = str(row["adapter"])
                object_key = str(row["object_key"])
                ts = now_iso()
                conn.execute(
                    """
                    UPDATE projection_outbox
                    SET status = 'draining', attempts = attempts + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (ts, outbox_id),
                )
                conn.commit()

                adapter = self.adapters.get(adapter_name)
                if adapter is None:
                    # No adapter registered for this row: leave pending, do not
                    # advance the watermark (retry once the adapter is present).
                    conn.execute(
                        """
                        UPDATE projection_outbox
                        SET status = 'pending', last_error = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (f"no adapter registered: {adapter_name}", now_iso(), outbox_id),
                    )
                    conn.commit()
                    report.failed.append(
                        {
                            "outbox_id": outbox_id,
                            "adapter": adapter_name,
                            "object_key": object_key,
                            "error": "no_adapter",
                        }
                    )
                    continue

                try:
                    result = adapter.render(object_key, dict(row))
                    done_ts = now_iso()
                    _advance_watermark(
                        conn,
                        adapter=adapter_name,
                        object_key=object_key,
                        watermark=str(outbox_id),
                        now=done_ts,
                    )
                    conn.execute(
                        """
                        UPDATE projection_outbox
                        SET status = 'done', watermark = ?, drained_at = ?,
                            updated_at = ?, last_error = NULL
                        WHERE id = ?
                        """,
                        (str(outbox_id), done_ts, done_ts, outbox_id),
                    )
                    conn.commit()
                    report.drained.append(
                        {
                            "outbox_id": outbox_id,
                            "adapter": adapter_name,
                            "object_key": object_key,
                            "result": result,
                        }
                    )
                except Exception as exc:  # noqa: BLE001 — projection failures are retryable
                    err = str(exc)
                    conn.execute(
                        """
                        UPDATE projection_outbox
                        SET status = 'failed', last_error = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (err[:1000], now_iso(), outbox_id),
                    )
                    conn.commit()
                    report.failed.append(
                        {
                            "outbox_id": outbox_id,
                            "adapter": adapter_name,
                            "object_key": object_key,
                            "error": err,
                        }
                    )
        finally:
            conn.close()
        return report

    def drain_until_empty(self, *, max_batches: int = 100, limit: int = 50) -> DrainReport:
        """Drain repeatedly until nothing progresses (bounded)."""
        total = DrainReport()
        for _ in range(max_batches):
            report = self.drain(limit=limit)
            total.drained.extend(report.drained)
            total.failed.extend(report.failed)
            if report.drained_count == 0:
                break
        return total

    # ------------------------------------------------------------------ metrics
    def watermark(self, adapter: str, object_key: str = "default") -> str | None:
        conn = connect_ro(self.ws.ledger_db)
        try:
            row = conn.execute(
                """
                SELECT watermark FROM projection_watermark
                WHERE adapter = ? AND object_key = ?
                """,
                (adapter, object_key),
            ).fetchone()
            return row["watermark"] if row else None
        finally:
            conn.close()

    def lag_metrics(self) -> dict[str, Any]:
        return projection_lag(self.ws.ledger_db)


def enqueue_projection(
    ledger_conn: sqlite3.Connection,
    *,
    adapter: str,
    object_key: str,
    reason: str | None,
    change_request_id: int | None,
    now: str,
) -> int:
    """Insert or coalesce a pending outbox row. Returns the outbox row id."""
    existing = ledger_conn.execute(
        """
        SELECT id FROM projection_outbox
        WHERE adapter = ? AND object_key = ? AND status IN ('pending', 'failed')
        ORDER BY id DESC LIMIT 1
        """,
        (adapter, object_key),
    ).fetchone()
    if existing:
        outbox_id = int(existing["id"])
        ledger_conn.execute(
            """
            UPDATE projection_outbox
            SET reason = COALESCE(?, reason),
                change_request_id = COALESCE(?, change_request_id),
                status = 'pending',
                updated_at = ?
            WHERE id = ?
            """,
            (reason, change_request_id, now, outbox_id),
        )
        return outbox_id
    cur = ledger_conn.execute(
        """
        INSERT INTO projection_outbox (
            adapter, object_key, watermark, reason, change_request_id,
            status, attempts, created_at, updated_at
        ) VALUES (?, ?, NULL, ?, ?, 'pending', 0, ?, ?)
        """,
        (adapter, object_key, reason, change_request_id, now, now),
    )
    return int(cur.lastrowid or 0)


def schedule_projections(
    ledger_conn: sqlite3.Connection,
    *,
    object_key: str,
    change_request_id: int | None,
    now: str,
    reason: str = "canonical_apply",
    adapters: tuple[str, ...] = DEFAULT_ADAPTERS,
) -> None:
    """Fan a canonical commit out to every projection adapter (invariant 11)."""
    for adapter in adapters:
        enqueue_projection(
            ledger_conn,
            adapter=adapter,
            object_key=object_key,
            reason=reason,
            change_request_id=change_request_id,
            now=now,
        )


def _advance_watermark(
    conn: sqlite3.Connection,
    *,
    adapter: str,
    object_key: str,
    watermark: str,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO projection_watermark (adapter, object_key, watermark, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(adapter, object_key) DO UPDATE SET
            watermark = CASE
                WHEN CAST(excluded.watermark AS INTEGER)
                     >= CAST(projection_watermark.watermark AS INTEGER)
                THEN excluded.watermark ELSE projection_watermark.watermark END,
            updated_at = excluded.updated_at
        """,
        (adapter, object_key, watermark, now),
    )


def projection_status_for_change_request(
    ledger_conn: sqlite3.Connection, change_request_id: int
) -> str:
    """Return 'refreshed' once every outbox row for a CR has drained."""
    row = ledger_conn.execute(
        """
        SELECT COUNT(*) AS n FROM projection_outbox
        WHERE change_request_id = ? AND status != 'done'
        """,
        (change_request_id,),
    ).fetchone()
    outstanding = int(row["n"]) if row else 0
    total = ledger_conn.execute(
        "SELECT COUNT(*) AS n FROM projection_outbox WHERE change_request_id = ?",
        (change_request_id,),
    ).fetchone()
    if total is None or int(total["n"]) == 0:
        return "n/a"
    return "refreshed" if outstanding == 0 else "pending"


def projection_lag(ledger_db) -> dict[str, Any]:
    """Health metric: pending outbox depth + oldest-pending age + watermarks."""
    if not ledger_db.exists():
        return {"pending": 0, "failed": 0, "oldest_pending_age_seconds": None, "by_adapter": {}}
    conn = connect_ro(ledger_db)
    try:
        by_adapter: dict[str, dict[str, Any]] = {}
        rows = conn.execute(
            """
            SELECT adapter,
                   SUM(CASE WHEN status IN ('pending','draining') THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                   MIN(CASE WHEN status != 'done' THEN created_at END) AS oldest
            FROM projection_outbox
            GROUP BY adapter
            """
        ).fetchall()
        pending_total = 0
        failed_total = 0
        oldest_overall: str | None = None
        for r in rows:
            adapter = str(r["adapter"])
            pending = int(r["pending"] or 0)
            failed = int(r["failed"] or 0)
            oldest = r["oldest"]
            pending_total += pending
            failed_total += failed
            if oldest and (oldest_overall is None or oldest < oldest_overall):
                oldest_overall = oldest
            wm = conn.execute(
                "SELECT MAX(watermark) AS w FROM projection_watermark WHERE adapter = ?",
                (adapter,),
            ).fetchone()
            by_adapter[adapter] = {
                "pending": pending,
                "failed": failed,
                "oldest_pending_at": oldest,
                "watermark": wm["w"] if wm else None,
            }
        return {
            "pending": pending_total,
            "failed": failed_total,
            "oldest_pending_age_seconds": _age_seconds(oldest_overall),
            "oldest_pending_at": oldest_overall,
            "by_adapter": by_adapter,
        }
    finally:
        conn.close()


def _age_seconds(iso_ts: str | None) -> float | None:
    if not iso_ts:
        return None
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = now() - dt
    return max(0.0, delta.total_seconds())


class ProjectionDrainLoop:
    """Background thread that periodically drains projections (used by `serve`)."""

    def __init__(
        self,
        coordinator: ProjectionCoordinator,
        *,
        interval_seconds: float = 2.0,
        batch_limit: int = 50,
    ) -> None:
        self.coordinator = coordinator
        self.interval = interval_seconds
        self.batch_limit = batch_limit
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="projection-drain", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.coordinator.drain(limit=self.batch_limit)
            except Exception:  # noqa: BLE001 — never let the loop die on a bad batch
                pass
            self._stop.wait(self.interval)

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
