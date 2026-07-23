"""Capture-first ledger service (invariant 1 + never-drop + idempotency)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from domain_foundry_core.clock import now_iso
from domain_foundry_core.ids import new_ulid
from domain_foundry_core.ledger.attachments import attachments_to_json, store_attachment
from domain_foundry_core.ledger.migrate import ensure_migrated, read_schema_version
from domain_foundry_core.ledger.models import (
    CaptureReceipt,
    EntryRow,
    HealthReport,
    ProjectionLagReport,
    RoutedSpan,
    StoreHealth,
)
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.redact import redact_secrets
from domain_foundry_core.security.store import connect_ro, connect_rw, integrity_check


def _content_hash(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class CaptureService:
    """Owns durable capture → entry inserts. Interpretation is staged after (P2+)."""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self.ws = workspace or Workspace()
        self.ws.ensure_layout()
        ensure_migrated(self.ws.ledger_db, "ledger")
        ensure_migrated(self.ws.domains_db, "domains")

    # ------------------------------------------------------------------ capture
    def capture(
        self,
        text: str,
        *,
        channel: str = "cli",
        source_ref: str | None = None,
        actor: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> CaptureReceipt:
        """
        Durable capture-first insert.

        Ordering (observable in tests):
          1. validate + redact
          2. INSERT capture_event
          3. INSERT entry (status=ledger_only until routing/apply)
          4. INSERT source_link (FTS synced by ledger triggers)
          5. return receipt

        Idempotency: (channel, source_ref) unique → replay returns original receipt.
        """
        channel = (channel or "cli").strip().lower()
        if not channel:
            raise ValueError("channel is required")
        safe_text = redact_secrets(text)
        if not safe_text.strip() and not attachments:
            raise ValueError("capture requires text or attachments")

        stored_attachments: list[dict[str, Any]] = []
        for item in attachments or []:
            if "data" in item:
                data = item["data"]
                if isinstance(data, str):
                    data = data.encode("utf-8")
                stored_attachments.append(
                    store_attachment(
                        self.ws.attachments_dir,
                        data,
                        filename=item.get("filename"),
                        content_type=item.get("content_type"),
                    )
                )
            else:
                stored_attachments.append(item)

        ts = now_iso()
        conn = connect_rw(self.ws.ledger_db)
        try:
            if source_ref:
                existing = conn.execute(
                    "SELECT id FROM capture_event WHERE channel = ? AND source_ref = ?",
                    (channel, source_ref),
                ).fetchone()
                if existing:
                    return self._receipt_for_capture(conn, existing["id"], replay=True)

            capture_id = new_ulid()
            entry_id = new_ulid()
            summary = _summarize(safe_text)

            # Invariant 1: raw provenance lands before any interpretation.
            conn.execute(
                """
                INSERT INTO capture_event (
                    id, channel, source_ref, actor, raw_text, raw_payload_json,
                    attachments_json, content_hash, captured_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    channel,
                    source_ref,
                    actor,
                    safe_text,
                    json.dumps(raw_payload) if raw_payload else None,
                    attachments_to_json(stored_attachments),
                    _content_hash(safe_text),
                    ts,
                    ts,
                ),
            )
            conn.execute(
                """
                INSERT INTO entry (
                    id, capture_event_id, status, domain, object_type, operation,
                    routing_confidence, fallback_tier, summary, privacy_level,
                    tags_json, created_at, updated_at
                ) VALUES (?, ?, 'ledger_only', NULL, NULL, NULL, NULL, 'ledger_only',
                          ?, 'normal', NULL, ?, ?)
                """,
                (entry_id, capture_id, summary, ts, ts),
            )
            conn.execute(
                """
                INSERT INTO source_link (
                    source_type, source_id, target_type, target_id,
                    relationship, confidence, created_at
                ) VALUES ('capture_event', ?, 'entry', ?, 'created_from', 1.0, ?)
                """,
                (capture_id, entry_id, ts),
            )
            # entry_fts + search_document are maintained by ledger_003 triggers.
            conn.commit()
            return CaptureReceipt(
                entry_id=entry_id,
                capture_event_id=capture_id,
                status="ledger_only",
                routed=[
                    RoutedSpan(
                        domain=None,
                        object_type=None,
                        operation=None,
                        disposition="ledger_only",
                        confidence=None,
                    )
                ],
                projection_status="n/a",
                idempotent_replay=False,
                summary=summary,
            )
        finally:
            conn.close()

    def _receipt_for_capture(
        self, conn: sqlite3.Connection, capture_id: str, *, replay: bool
    ) -> CaptureReceipt:
        row = conn.execute(
            """
            SELECT e.id AS entry_id, e.status, e.domain, e.object_type, e.operation,
                   e.routing_confidence, e.summary, e.fallback_tier
            FROM entry e
            WHERE e.capture_event_id = ?
            ORDER BY e.created_at ASC
            LIMIT 1
            """,
            (capture_id,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"capture {capture_id} has no entry (integrity failure)")
        return CaptureReceipt(
            entry_id=row["entry_id"],
            capture_event_id=capture_id,
            status=row["status"],
            routed=[
                RoutedSpan(
                    domain=row["domain"],
                    object_type=row["object_type"],
                    operation=row["operation"],
                    disposition=row["status"],
                    confidence=row["routing_confidence"],
                )
            ],
            projection_status="n/a",
            idempotent_replay=replay,
            summary=row["summary"],
        )

    # -------------------------------------------------------------------- query
    def query(
        self,
        *,
        domain: str | None = None,
        object_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> list[EntryRow]:
        limit = max(1, min(int(limit), 500))
        params: list[Any] = []

        if q:
            sql = """
                SELECT e.id, e.capture_event_id, e.status, e.domain, e.object_type,
                       e.operation, e.routing_confidence, e.fallback_tier, e.summary,
                       e.created_at, e.updated_at, c.raw_text, c.channel
                FROM search_fts
                JOIN search_document sd ON sd.id = search_fts.rowid
                JOIN entry e ON e.id = sd.ref_id AND sd.kind = 'entry'
                JOIN capture_event c ON c.id = e.capture_event_id
                WHERE search_fts MATCH ?
            """
            params.append(q)
            if domain:
                sql += " AND e.domain = ?"
                params.append(domain)
            if object_type:
                sql += " AND e.object_type = ?"
                params.append(object_type)
            if status:
                sql += " AND e.status = ?"
                params.append(status)
            sql += " ORDER BY e.created_at DESC LIMIT ?"
            params.append(limit)
        else:
            sql = """
                SELECT e.id, e.capture_event_id, e.status, e.domain, e.object_type,
                       e.operation, e.routing_confidence, e.fallback_tier, e.summary,
                       e.created_at, e.updated_at, c.raw_text, c.channel
                FROM entry e
                JOIN capture_event c ON c.id = e.capture_event_id
                WHERE 1=1
            """
            if domain:
                sql += " AND e.domain = ?"
                params.append(domain)
            if object_type:
                sql += " AND e.object_type = ?"
                params.append(object_type)
            if status:
                sql += " AND e.status = ?"
                params.append(status)
            sql += " ORDER BY e.created_at DESC LIMIT ?"
            params.append(limit)

        conn = connect_ro(self.ws.ledger_db)
        try:
            rows = conn.execute(sql, params).fetchall()
            return [
                EntryRow(
                    id=r["id"],
                    capture_event_id=r["capture_event_id"],
                    status=r["status"],
                    domain=r["domain"],
                    object_type=r["object_type"],
                    operation=r["operation"],
                    routing_confidence=r["routing_confidence"],
                    fallback_tier=r["fallback_tier"],
                    summary=r["summary"],
                    raw_text=r["raw_text"],
                    channel=r["channel"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    # ------------------------------------------------------------------- health
    def health(self) -> HealthReport:
        ledger = integrity_check(self.ws.ledger_db)
        domains = integrity_check(self.ws.domains_db)
        ledger_ver = read_schema_version(self.ws.ledger_db)
        domains_ver = read_schema_version(self.ws.domains_db)

        counts: dict[str, int] = {}
        last_capture: str | None = None
        if self.ws.ledger_db.exists():
            conn = connect_ro(self.ws.ledger_db)
            try:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM entry GROUP BY status"
                ).fetchall()
                counts = {r["status"]: int(r["n"]) for r in rows}
                row = conn.execute(
                    "SELECT MAX(captured_at) AS t FROM capture_event"
                ).fetchone()
                last_capture = row["t"] if row else None
            finally:
                conn.close()

        ledger_h = StoreHealth(
            path=ledger["path"],
            exists=ledger["exists"],
            ok=ledger["ok"],
            integrity=str(ledger["integrity"]),
            fk_violations=ledger["fk_violations"],
            schema_version=ledger_ver,
        )
        domains_h = StoreHealth(
            path=domains["path"],
            exists=domains["exists"],
            ok=domains["ok"],
            integrity=str(domains["integrity"]),
            fk_violations=domains["fk_violations"],
            schema_version=domains_ver,
        )
        from domain_foundry_core.projections.coordinator import projection_lag

        lag = projection_lag(self.ws.ledger_db)
        return HealthReport(
            ok=ledger_h.ok and domains_h.ok,
            ledger=ledger_h,
            domains=domains_h,
            entry_counts=counts,
            last_capture_at=last_capture,
            projection_lag=ProjectionLagReport(**lag),
        )


def _summarize(text: str, max_len: int = 120) -> str:
    one_line = " ".join(text.strip().split())
    if len(one_line) <= max_len:
        return one_line
    return one_line[: max_len - 1] + "…"
