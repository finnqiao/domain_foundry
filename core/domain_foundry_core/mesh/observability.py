"""Mesh observability — DLQ, per-domain health, queue-depth alerts.

Phase 8 (mesh P5): poisoned inbox/outbound land in a dead-letter state;
operators list/retry via ``domain-foundry mesh dlq``; Concierge can enqueue
a depth-threshold alert when gated on.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from domain_foundry_core.mesh.flags import MeshObservabilityFlags
from domain_foundry_core.mesh.inbox import DomainInbox
from domain_foundry_core.mesh.journal import InboxJournal
from domain_foundry_core.mesh.outbound import OutboundMessage, OutboundQueue
from domain_foundry_core.paths import Workspace

QueueKind = Literal["inbox", "outbound"]
ALERT_KIND_QUEUE_DEPTH = "queue_depth"


@dataclass(frozen=True)
class DlqEntry:
    id: str
    queue: QueueKind
    domain: str
    status: str
    error: str | None
    enqueued_at: str | None = None
    text_preview: str | None = None
    attempts: int | None = None
    journal_id: str | None = None
    channel: str | None = None
    destination: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MeshHealthReport:
    """Read-only mesh dashboard payload (SPA / ``mesh status``)."""

    home: str
    journal: dict[str, int] = field(default_factory=dict)
    inbox_by_domain: dict[str, dict[str, int]] = field(default_factory=dict)
    outbound: dict[str, int] = field(default_factory=dict)
    domains: dict[str, dict[str, Any]] = field(default_factory=dict)
    queue_depths: dict[str, int] = field(default_factory=dict)
    dlq: dict[str, int] = field(default_factory=dict)
    alerts: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeadLetterQueue:
    """Unified view over dead inbox + outbound rows."""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self.ws = workspace or Workspace()
        self.inbox = DomainInbox(self.ws)
        self.outbound = OutboundQueue(self.ws)

    def list(
        self,
        *,
        domain: str | None = None,
        queue: QueueKind | None = None,
        limit: int = 100,
        include_failed: bool = True,
    ) -> list[DlqEntry]:
        entries: list[DlqEntry] = []
        if queue in (None, "inbox"):
            for msg in self.inbox.list_dead(
                domain=domain, limit=limit, include_failed=include_failed
            ):
                text = None
                raw = msg.payload.get("text") if isinstance(msg.payload, dict) else None
                if isinstance(raw, str) and raw.strip():
                    text = raw.strip()[:120]
                entries.append(
                    DlqEntry(
                        id=msg.id,
                        queue="inbox",
                        domain=msg.domain,
                        status=msg.status,
                        error=msg.error,
                        enqueued_at=msg.enqueued_at,
                        text_preview=text,
                        journal_id=msg.journal_id,
                    )
                )
        if queue in (None, "outbound"):
            for msg in self.outbound.list_dead(origin_domain=domain, limit=limit):
                entries.append(
                    DlqEntry(
                        id=msg.id,
                        queue="outbound",
                        domain=msg.origin_domain,
                        status=msg.status,
                        error=msg.last_error,
                        enqueued_at=msg.created_at,
                        text_preview=(msg.text or "")[:120] or None,
                        attempts=msg.attempts,
                        channel=msg.channel or None,
                        destination=msg.destination or None,
                    )
                )
        entries.sort(key=lambda e: e.enqueued_at or "", reverse=True)
        return entries[: int(limit)]

    def retry(self, msg_id: str) -> DlqEntry | None:
        """Retry a DLQ row; tries inbox then outbound."""
        inbox_msg = self.inbox.get(msg_id)
        if inbox_msg is not None and inbox_msg.status in {"failed", "dead"}:
            retried = self.inbox.retry(msg_id)
            if retried is None:
                return None
            text = None
            raw = retried.payload.get("text") if isinstance(retried.payload, dict) else None
            if isinstance(raw, str) and raw.strip():
                text = raw.strip()[:120]
            return DlqEntry(
                id=retried.id,
                queue="inbox",
                domain=retried.domain,
                status=retried.status,
                error=retried.error,
                enqueued_at=retried.enqueued_at,
                text_preview=text,
                journal_id=retried.journal_id,
            )

        out_msg = self.outbound.get(msg_id)
        if out_msg is not None and out_msg.status == "dead":
            retried_out = self.outbound.retry(msg_id)
            if retried_out is None:
                return None
            return DlqEntry(
                id=retried_out.id,
                queue="outbound",
                domain=retried_out.origin_domain,
                status=retried_out.status,
                error=retried_out.last_error,
                enqueued_at=retried_out.created_at,
                text_preview=(retried_out.text or "")[:120] or None,
                attempts=retried_out.attempts,
                channel=retried_out.channel or None,
                destination=retried_out.destination or None,
            )
        return None

    def counts(self) -> dict[str, int]:
        inbox_depths = self.inbox.depth()
        outbound_depths = self.outbound.depth()
        return {
            "inbox_dead": int(inbox_depths.get("dead", 0)),
            "inbox_failed": int(inbox_depths.get("failed", 0)),
            "outbound_dead": int(outbound_depths.get("dead", 0)),
        }


class MeshObservability:
    """Health snapshot + optional queue-depth Concierge alerts."""

    def __init__(
        self,
        workspace: Workspace | None = None,
        *,
        flags: MeshObservabilityFlags | None = None,
    ) -> None:
        self.ws = workspace or Workspace()
        self.flags = flags if flags is not None else MeshObservabilityFlags.from_env()
        self.journal = InboxJournal(self.ws)
        self.inbox = DomainInbox(self.ws)
        self.outbound = OutboundQueue(self.ws)
        self.dlq = DeadLetterQueue(self.ws)

    def health(self) -> MeshHealthReport:
        domains = self.inbox.domain_health()
        inbox_by_domain = self.inbox.depths_by_domain()
        outbound = self.outbound.depth()
        pending_inbox = sum(
            int(d.get("pending", 0)) + int(d.get("processing", 0))
            for d in inbox_by_domain.values()
        )
        pending_outbound = int(outbound.get("pending", 0)) + int(
            outbound.get("delivering", 0)
        )
        dlq_counts = self.dlq.counts()
        return MeshHealthReport(
            home=str(self.ws.home),
            journal=self.journal.counts(),
            inbox_by_domain=inbox_by_domain,
            outbound=outbound,
            domains=domains,
            queue_depths={
                "inbox_pending": pending_inbox,
                "outbound_pending": pending_outbound,
                "inbox_dead": dlq_counts["inbox_dead"],
                "outbound_dead": dlq_counts["outbound_dead"],
            },
            dlq=dlq_counts,
            alerts={
                "depth_alert_enabled": self.flags.depth_alert,
                "depth_alert_threshold": self.flags.depth_alert_threshold,
            },
            notes=[
                "read-only mesh dashboard stub — GET /api/mesh/status + /api/mesh/dlq",
                "DLQ: domain-foundry mesh dlq list|retry",
                f"depth alert flag {self.flags.depth_alert} "
                f"(threshold={self.flags.depth_alert_threshold})",
            ],
        )

    def maybe_enqueue_depth_alert(
        self,
        *,
        channel: str | None = None,
        destination: str | None = None,
    ) -> list[OutboundMessage]:
        """If enabled and any domain inbox depth >= threshold, enqueue an alert.

        Dedupes while a matching alert is still pending/delivering.
        Returns newly enqueued outbound messages (empty when gated off / quiet).
        """
        if not self.flags.depth_alert:
            return []

        threshold = self.flags.depth_alert_threshold
        channel_name = channel or self.flags.depth_alert_channel
        dest = destination or self.flags.depth_alert_destination
        enqueued: list[OutboundMessage] = []

        # Global pending depth (all domains) + per-domain breaches.
        health = self.health()
        breaches: list[tuple[str, int]] = []
        for domain, info in health.domains.items():
            depth = int(info.get("pending_depth") or 0)
            if depth >= threshold:
                breaches.append((domain, depth))
        total_pending = int(health.queue_depths.get("inbox_pending") or 0)
        if not breaches and total_pending >= threshold:
            breaches.append(("*", total_pending))

        for domain, depth in breaches:
            alert_domain = None if domain == "*" else domain
            if self.outbound.has_pending_alert(
                alert_kind=ALERT_KIND_QUEUE_DEPTH, domain=alert_domain
            ):
                continue
            if domain == "*":
                text = (
                    f"[mesh] queue depth alert: inbox pending={depth} "
                    f"(threshold={threshold})"
                )
            else:
                text = (
                    f"[mesh] queue depth alert: {domain} pending={depth} "
                    f"(threshold={threshold})"
                )
            msg = self.outbound.enqueue(
                origin_domain="general" if domain == "*" else domain,
                text=text,
                channel=channel_name,
                destination=dest,
                payload={
                    "alert_kind": ALERT_KIND_QUEUE_DEPTH,
                    "alert_domain": alert_domain,
                    "pending_depth": depth,
                    "threshold": threshold,
                },
            )
            enqueued.append(msg)
        return enqueued
