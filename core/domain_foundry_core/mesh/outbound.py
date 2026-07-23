"""Durable outbound_queue — Expert/Concierge → gateway delivery with retry.

Producers (Domain Experts, Concierge) enqueue replies tagged by origin domain.
The Hermes gateway (private logbook plugin) polls ``claim_batch``, delivers with
``[japanese]`` / ``[food]`` prefixes, then ``ack`` / ``fail``.

See docs/PER_DOMAIN_AGENT_MESH_2026-07-20.md §7; HermesWorkspace CONVERGENCE_LOG
poll contract.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any

from domain_foundry_core.clock import now, now_iso
from domain_foundry_core.ids import new_ulid
from domain_foundry_core.ledger.migrate import ensure_migrated
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_rw

# Origin tags applied when delivering Expert replies back to a shared channel.
DOMAIN_PREFIXES: dict[str, str] = {
    "japanese": "[japanese]",
    "food": "[food]",
    "health": "[health]",
    "dev": "[dev]",
    "travel": "[travel]",
    "general": "[general]",
}

DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_BACKOFF_BASE_S = 1.0
DEFAULT_BACKOFF_CAP_S = 300.0


def domain_prefix(domain: str) -> str:
    return DOMAIN_PREFIXES.get(domain, f"[{domain}]")


def backoff_seconds(
    attempts: int,
    *,
    base_s: float = DEFAULT_BACKOFF_BASE_S,
    cap_s: float = DEFAULT_BACKOFF_CAP_S,
) -> float:
    """Exponential backoff after a failed delivery attempt."""
    if attempts <= 0:
        return 0.0
    return min(cap_s, base_s * (2 ** (attempts - 1)))


@dataclass(frozen=True)
class OutboundMessage:
    id: str
    origin_domain: str
    text: str
    channel: str
    destination: str
    status: str
    attempts: int
    next_attempt_at: str
    created_at: str
    last_error: str | None = None
    payload: dict[str, Any] | None = None
    claimed_at: str | None = None
    delivered_at: str | None = None

    def prefixed_text(self) -> str:
        tag = domain_prefix(self.origin_domain)
        body = (self.text or "").strip()
        if body.startswith(tag):
            return body
        return f"{tag} {body}".strip()


class OutboundQueue:
    """Ledger-backed outbound multiplex queue."""

    def __init__(
        self,
        workspace: Workspace | None = None,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base_s: float = DEFAULT_BACKOFF_BASE_S,
        backoff_cap_s: float = DEFAULT_BACKOFF_CAP_S,
    ) -> None:
        self.ws = workspace or Workspace()
        self.max_attempts = max_attempts
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s
        ensure_migrated(self.ws.ledger_db, "ledger")

    def _connect(self) -> sqlite3.Connection:
        return connect_rw(self.ws.ledger_db)

    def enqueue(
        self,
        *,
        origin_domain: str,
        text: str,
        channel: str,
        destination: str,
        payload: dict[str, Any] | None = None,
    ) -> OutboundMessage:
        """Insert a pending outbound message. Ready for immediate claim."""
        msg_id = new_ulid()
        ts = now_iso()
        body = {
            "text": text,
            "channel": channel,
            "destination": destination,
            **dict(payload or {}),
        }
        # Keep canonical keys authoritative even if payload overwrote them.
        body["text"] = text
        body["channel"] = channel
        body["destination"] = destination
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO outbound_queue (
                    id, origin_domain, payload_json, status, attempts,
                    next_attempt_at, created_at
                ) VALUES (?, ?, ?, 'pending', 0, ?, ?)
                """,
                (msg_id, origin_domain, json.dumps(body), ts, ts),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM outbound_queue WHERE id = ?", (msg_id,)
            ).fetchone()
            return self._row_to_msg(row)
        finally:
            conn.close()

    def claim_batch(self, *, limit: int = 10) -> list[OutboundMessage]:
        """Atomically claim up to ``limit`` ready pending rows.

        Ready = status='pending' AND next_attempt_at <= now.
        Claimed rows move to status='delivering' and attempts += 1.
        """
        ts = now_iso()
        claimed: list[OutboundMessage] = []
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT * FROM outbound_queue
                WHERE status = 'pending' AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC, created_at ASC, id ASC
                LIMIT ?
                """,
                (ts, int(limit)),
            ).fetchall()
            for row in rows:
                result = conn.execute(
                    """
                    UPDATE outbound_queue
                    SET status = 'delivering',
                        attempts = attempts + 1,
                        claimed_at = ?,
                        last_error = NULL
                    WHERE id = ? AND status = 'pending'
                    """,
                    (ts, row["id"]),
                )
                if result.rowcount == 0:
                    continue
                refreshed = conn.execute(
                    "SELECT * FROM outbound_queue WHERE id = ?", (row["id"],)
                ).fetchone()
                claimed.append(self._row_to_msg(refreshed))
            conn.commit()
            return claimed
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ack(self, msg_id: str) -> None:
        """Mark a claimed message delivered."""
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE outbound_queue
                SET status = 'delivered',
                    delivered_at = ?,
                    last_error = NULL
                WHERE id = ?
                """,
                (now_iso(), msg_id),
            )
            conn.commit()
        finally:
            conn.close()

    def fail(self, msg_id: str, error: str) -> OutboundMessage | None:
        """Record a delivery failure; schedule retry with exponential backoff.

        After ``max_attempts``, the row is marked ``dead`` (no further claims).
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM outbound_queue WHERE id = ?", (msg_id,)
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            attempts = int(row["attempts"])
            err = (error or "")[:1000]
            if attempts >= self.max_attempts:
                conn.execute(
                    """
                    UPDATE outbound_queue
                    SET status = 'dead', last_error = ?
                    WHERE id = ?
                    """,
                    (err, msg_id),
                )
            else:
                delay = backoff_seconds(
                    attempts,
                    base_s=self.backoff_base_s,
                    cap_s=self.backoff_cap_s,
                )
                next_at = now() + timedelta(seconds=delay)
                if next_at.tzinfo is None:
                    next_at = next_at.replace(tzinfo=UTC)
                next_iso = next_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
                conn.execute(
                    """
                    UPDATE outbound_queue
                    SET status = 'pending',
                        next_attempt_at = ?,
                        last_error = ?,
                        claimed_at = NULL
                    WHERE id = ?
                    """,
                    (next_iso, err, msg_id),
                )
            conn.commit()
            refreshed = conn.execute(
                "SELECT * FROM outbound_queue WHERE id = ?", (msg_id,)
            ).fetchone()
            return self._row_to_msg(refreshed) if refreshed else None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get(self, msg_id: str) -> OutboundMessage | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM outbound_queue WHERE id = ?", (msg_id,)
            ).fetchone()
            return self._row_to_msg(row) if row else None
        finally:
            conn.close()

    def list_dead(
        self,
        *,
        origin_domain: str | None = None,
        limit: int = 100,
    ) -> list[OutboundMessage]:
        """List dead outbound rows for the DLQ CLI/API."""
        conn = self._connect()
        try:
            if origin_domain:
                rows = conn.execute(
                    """
                    SELECT * FROM outbound_queue
                    WHERE status = 'dead' AND origin_domain = ?
                    ORDER BY COALESCE(claimed_at, created_at) DESC, id DESC
                    LIMIT ?
                    """,
                    (origin_domain, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM outbound_queue
                    WHERE status = 'dead'
                    ORDER BY COALESCE(claimed_at, created_at) DESC, id DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
            return [self._row_to_msg(r) for r in rows]
        finally:
            conn.close()

    def retry(self, msg_id: str) -> OutboundMessage | None:
        """Requeue a dead outbound message as pending for another claim."""
        ts = now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM outbound_queue WHERE id = ?", (msg_id,)
            ).fetchone()
            if row is None or row["status"] != "dead":
                conn.commit()
                return None
            conn.execute(
                """
                UPDATE outbound_queue
                SET status = 'pending',
                    attempts = 0,
                    next_attempt_at = ?,
                    last_error = NULL,
                    claimed_at = NULL,
                    delivered_at = NULL
                WHERE id = ? AND status = 'dead'
                """,
                (ts, msg_id),
            )
            if conn.total_changes == 0:
                conn.commit()
                return None
            conn.commit()
            refreshed = conn.execute(
                "SELECT * FROM outbound_queue WHERE id = ?", (msg_id,)
            ).fetchone()
            return self._row_to_msg(refreshed) if refreshed else None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def has_pending_alert(self, *, alert_kind: str, domain: str | None = None) -> bool:
        """True if a non-delivered alert of this kind is already queued."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT payload_json FROM outbound_queue
                WHERE status IN ('pending', 'delivering')
                """
            ).fetchall()
            for row in rows:
                raw = row["payload_json"]
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                if payload.get("alert_kind") != alert_kind:
                    continue
                if domain is not None and payload.get("alert_domain") != domain:
                    continue
                return True
            return False
        finally:
            conn.close()

    def depth(self, origin_domain: str | None = None) -> dict[str, int]:
        conn = self._connect()
        try:
            if origin_domain:
                rows = conn.execute(
                    """
                    SELECT status, COUNT(*) AS n FROM outbound_queue
                    WHERE origin_domain = ? GROUP BY status
                    """,
                    (origin_domain,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM outbound_queue GROUP BY status"
                ).fetchall()
            return {str(r["status"]): int(r["n"]) for r in rows}
        finally:
            conn.close()

    @staticmethod
    def _row_to_msg(row: sqlite3.Row) -> OutboundMessage:
        payload: dict[str, Any] = {}
        raw = row["payload_json"]
        if raw:
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    payload = loaded
            except json.JSONDecodeError:
                payload = {"raw": raw}
        return OutboundMessage(
            id=row["id"],
            origin_domain=row["origin_domain"],
            text=str(payload.get("text") or ""),
            channel=str(payload.get("channel") or ""),
            destination=str(payload.get("destination") or ""),
            status=row["status"],
            attempts=int(row["attempts"]),
            next_attempt_at=row["next_attempt_at"],
            created_at=row["created_at"],
            last_error=row["last_error"],
            payload=payload,
            claimed_at=row["claimed_at"],
            delivered_at=row["delivered_at"],
        )
