"""Concierge loop skeleton — journal tail → route → enqueue → mark routed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain_foundry_core.mesh.inbox import DomainInbox
from domain_foundry_core.mesh.journal import InboxJournal, JournalRecord
from domain_foundry_core.mesh.outbound import OutboundMessage, OutboundQueue
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.router import Router


@dataclass
class RouteEnqueueResult:
    journal_id: str
    domain: str
    inbox_id: str
    confidence: float | None = None
    interpreter: str | None = None


class Concierge:
    """Thin, never-blocking router/switchboard for the domain mesh.

    Bounded work only: classify via the two-tier router, enqueue onto a
    domain inbox, mark the journal row routed. Never awaits Expert processing.
    Outbound replies are enqueued for the gateway; delivery is not awaited.
    """

    FALLBACK_DOMAIN = "general"

    def __init__(
        self,
        workspace: Workspace | None = None,
        *,
        router: Router | None = None,
        journal: InboxJournal | None = None,
        inbox: DomainInbox | None = None,
        outbound: OutboundQueue | None = None,
    ) -> None:
        self.ws = workspace or Workspace()
        self.journal = journal or InboxJournal(self.ws)
        self.inbox = inbox or DomainInbox(self.ws)
        self.outbound = outbound or OutboundQueue(self.ws)
        self.router = router or Router(self.ws)

    def enqueue_reply(
        self,
        *,
        origin_domain: str,
        text: str,
        channel: str,
        destination: str,
        payload: dict[str, Any] | None = None,
    ) -> OutboundMessage:
        """Enqueue an origin-tagged outbound reply (gateway delivers later)."""
        return self.outbound.enqueue(
            origin_domain=origin_domain,
            text=text,
            channel=channel,
            destination=destination,
            payload=payload,
        )

    def ingest(
        self,
        text: str,
        *,
        channel: str = "cli",
        source_ref: str | None = None,
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
        route: bool = True,
    ) -> JournalRecord:
        """Journal-first ingest. Optionally route+enqueue in the same call."""
        record = self.journal.append(
            text,
            channel=channel,
            source_ref=source_ref,
            actor=actor,
            payload=payload,
        )
        if route and record.status == "pending" and not record.idempotent_replay:
            self.route_one(record)
            refreshed = self.journal.get(record.id)
            return refreshed or record
        if route and record.status == "pending" and record.idempotent_replay:
            # Replay of an unrouted duplicate — drain it.
            self.route_one(record)
            refreshed = self.journal.get(record.id)
            return refreshed or record
        return record

    def route_one(self, record: JournalRecord) -> RouteEnqueueResult:
        """Classify one journal row and enqueue onto the target domain inbox."""
        try:
            domain, confidence, interpreter = self._classify(
                record.raw_text, channel=record.channel
            )
            payload = {
                "text": record.raw_text,
                "channel": record.channel,
                "source_ref": record.source_ref,
                "actor": record.actor,
                "journal_id": record.id,
                "payload": record.payload,
            }
            msg = self.inbox.enqueue(
                domain, journal_id=record.id, payload=payload
            )
            self.journal.mark_routed(
                record.id, domain=domain, domain_inbox_id=msg.id
            )
            return RouteEnqueueResult(
                journal_id=record.id,
                domain=domain,
                inbox_id=msg.id,
                confidence=confidence,
                interpreter=interpreter,
            )
        except Exception as exc:  # noqa: BLE001 — mark failed, don't lose the row
            self.journal.mark_failed(record.id, str(exc))
            raise

    def drain(self, *, limit: int = 100) -> list[RouteEnqueueResult]:
        """Tail pending journal rows and route them. Bounded; never blocks on Experts."""
        results: list[RouteEnqueueResult] = []
        for record in self.journal.list_pending(limit=limit):
            results.append(self.route_one(record))
        return results

    def _classify(
        self, text: str, *, channel: str
    ) -> tuple[str, float | None, str | None]:
        """Pick a target domain via the existing two-tier router."""
        result = self.router.route_text(text, channel=channel)
        real = [
            s
            for s in result.spans
            if s.domain not in {"_unfiled", "_ledger", self.FALLBACK_DOMAIN}
        ]
        if real:
            primary = max(real, key=lambda s: s.confidence)
            return primary.domain, primary.confidence, result.interpreter
        if result.spans:
            # Prefer explicit general / unfiled over inventing a domain.
            fallback = result.spans[0].domain
            if fallback.startswith("_"):
                fallback = self.FALLBACK_DOMAIN
            return fallback, result.spans[0].confidence, result.interpreter
        return self.FALLBACK_DOMAIN, None, result.interpreter
