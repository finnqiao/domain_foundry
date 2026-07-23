"""Concierge loop — journal → UX classify → enqueue → mark routed.

Phase 5 UX glue (each behind ``ConciergeUXFlags``):
  stickiness, barge-in, not_mine reroute, switch command.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from domain_foundry_core.clock import now_iso
from domain_foundry_core.ids import new_ulid
from domain_foundry_core.interpret.fewshot import append_eval_case
from domain_foundry_core.mesh.flags import ConciergeUXFlags, MeshObservabilityFlags
from domain_foundry_core.mesh.inbox import DomainInbox, InboxMessage
from domain_foundry_core.mesh.journal import InboxJournal, JournalRecord
from domain_foundry_core.mesh.observability import MeshObservability
from domain_foundry_core.mesh.outbound import OutboundMessage, OutboundQueue
from domain_foundry_core.mesh.sessions import DomainSessionStore
from domain_foundry_core.mesh.ux import (
    ClassifyDecision,
    is_ambiguous,
    is_high_confidence_barge,
    parse_barge_marker,
    parse_switch,
    primary_span,
)
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.router import Router
from domain_foundry_core.security.store import connect_rw


@dataclass
class RouteEnqueueResult:
    journal_id: str
    domain: str
    inbox_id: str
    confidence: float | None = None
    interpreter: str | None = None
    reason: str = "classify"
    sticky_session_id: str | None = None
    sticky_domain: str | None = None


@dataclass
class NotMineResult:
    journal_id: str
    bounced_domain: str
    routed_domain: str
    inbox_id: str
    correction_id: str
    eval_case_id: str | None = None


class Concierge:
    """Thin, never-blocking router/switchboard for the domain mesh.

    Bounded work only: classify via the two-tier router (+ UX glue), enqueue
    onto a domain inbox, mark the journal row routed. Never awaits Expert
    processing. Outbound replies are enqueued for the gateway; delivery is
    not awaited.
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
        sessions: DomainSessionStore | None = None,
        flags: ConciergeUXFlags | None = None,
        obs_flags: MeshObservabilityFlags | None = None,
    ) -> None:
        self.ws = workspace or Workspace()
        self.journal = journal or InboxJournal(self.ws)
        self.inbox = inbox or DomainInbox(self.ws)
        self.outbound = outbound or OutboundQueue(self.ws)
        self.sessions = sessions or DomainSessionStore(self.ws)
        self.router = router or Router(self.ws)
        self.flags = flags if flags is not None else ConciergeUXFlags.from_env()
        self.obs_flags = (
            obs_flags if obs_flags is not None else MeshObservabilityFlags.from_env()
        )
        self.obs = MeshObservability(self.ws, flags=self.obs_flags)

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
            decision = self._decide(
                record.raw_text,
                channel=record.channel,
                actor=record.actor,
            )
            payload = {
                "text": record.raw_text,
                "channel": record.channel,
                "source_ref": record.source_ref,
                "actor": record.actor,
                "journal_id": record.id,
                "payload": record.payload,
                "route_reason": decision.reason,
                "sticky_session_id": decision.sticky_session_id,
                "sticky_domain": decision.sticky_domain,
            }
            # Switch intents are handled by forcing sticky; still enqueue a
            # lightweight ack turn so Experts can acknowledge focus change.
            msg = self.inbox.enqueue(
                decision.domain, journal_id=record.id, payload=payload
            )
            self.journal.mark_routed(
                record.id, domain=decision.domain, domain_inbox_id=msg.id
            )
            if (
                decision.reason in {"sticky", "switch"}
                and decision.sticky_session_id
            ):
                try:
                    self.sessions.touch(decision.sticky_session_id)
                except KeyError:
                    pass
            return RouteEnqueueResult(
                journal_id=record.id,
                domain=decision.domain,
                inbox_id=msg.id,
                confidence=decision.confidence,
                interpreter=decision.interpreter,
                reason=decision.reason,
                sticky_session_id=decision.sticky_session_id,
                sticky_domain=decision.sticky_domain,
            )
        except Exception as exc:  # noqa: BLE001 — mark failed, don't lose the row
            self.journal.mark_failed(record.id, str(exc))
            raise

    def drain(self, *, limit: int = 100) -> list[RouteEnqueueResult]:
        """Tail pending journal rows and route them. Bounded; never blocks on Experts."""
        results: list[RouteEnqueueResult] = []
        for record in self.journal.list_pending(limit=limit):
            results.append(self.route_one(record))
        # Observability side-effect: optional queue-depth threshold alert.
        self.maybe_enqueue_depth_alert()
        return results

    def maybe_enqueue_depth_alert(
        self,
        *,
        channel: str | None = None,
        destination: str | None = None,
    ) -> list[OutboundMessage]:
        """Enqueue Concierge outbound alerts when inbox depth exceeds threshold.

        Gated by ``DOMAIN_FOUNDRY_MESH_DEPTH_ALERT`` (default off).
        """
        return self.obs.maybe_enqueue_depth_alert(
            channel=channel, destination=destination
        )

    def handle_not_mine(
        self,
        msg: InboxMessage,
        *,
        bounced_domain: str | None = None,
    ) -> NotMineResult:
        """Expert bounce → re-route excluding bouncer → record routing correction.

        Gated by ``flags.not_mine``. The bounced inbox message should already
        be acked with ``kind=not_mine``; this enqueues a fresh inbox row for
        the corrected domain (same journal_id, different domain — allowed by
        UNIQUE(journal_id, domain)).
        """
        if not self.flags.not_mine:
            raise RuntimeError("not_mine reroute disabled (DOMAIN_FOUNDRY_MESH_NOT_MINE)")

        bouncer = bounced_domain or msg.domain
        record = self.journal.get(msg.journal_id)
        if record is None:
            raise KeyError(f"journal row missing for {msg.journal_id}")

        text = str(msg.payload.get("text") or record.raw_text)
        channel = str(msg.payload.get("channel") or record.channel)
        actor = msg.payload.get("actor") or record.actor

        decision = self._decide(
            text,
            channel=channel,
            actor=str(actor) if actor else None,
            exclude_domains={bouncer},
            force_reason="not_mine_reroute",
        )
        if decision.domain == bouncer:
            # Classifier still insists on bouncer — fall to general.
            decision = ClassifyDecision(
                domain=self.FALLBACK_DOMAIN,
                confidence=decision.confidence,
                interpreter=decision.interpreter,
                reason="not_mine_reroute",
                sticky_session_id=decision.sticky_session_id,
                sticky_domain=decision.sticky_domain,
            )

        payload = {
            "text": text,
            "channel": channel,
            "source_ref": record.source_ref,
            "actor": actor,
            "journal_id": record.id,
            "payload": record.payload,
            "route_reason": "not_mine_reroute",
            "bounced_from": bouncer,
            "sticky_session_id": decision.sticky_session_id,
            "sticky_domain": decision.sticky_domain,
        }
        new_msg = self.inbox.enqueue(
            decision.domain, journal_id=record.id, payload=payload
        )
        # Keep journal routed_domain pointing at the corrected destination.
        self.journal.mark_routed(
            record.id, domain=decision.domain, domain_inbox_id=new_msg.id
        )

        correction_id, eval_id = self._record_routing_correction(
            journal_id=record.id,
            bounced_domain=bouncer,
            routed_domain=decision.domain,
            raw_text=text,
        )
        return NotMineResult(
            journal_id=record.id,
            bounced_domain=bouncer,
            routed_domain=decision.domain,
            inbox_id=new_msg.id,
            correction_id=correction_id,
            eval_case_id=eval_id,
        )

    # ------------------------------------------------------------------
    # Classify / UX decision
    # ------------------------------------------------------------------

    def _decide(
        self,
        text: str,
        *,
        channel: str,
        actor: str | None,
        exclude_domains: set[str] | None = None,
        force_reason: str | None = None,
    ) -> ClassifyDecision:
        user_id = actor or "default"
        exclude = exclude_domains or set()

        # 1) Switch command — force sticky domain.
        if self.flags.switch and force_reason is None:
            intent = parse_switch(text)
            if intent is not None and intent.domain not in exclude:
                session = self.sessions.force_sticky(
                    intent.domain, user_id=user_id
                )
                return ClassifyDecision(
                    domain=intent.domain,
                    confidence=1.0,
                    interpreter="switch",
                    reason="switch",
                    sticky_session_id=session.id,
                    sticky_domain=session.domain,
                )

        sticky = None
        if self.flags.stickiness or self.flags.barge_in:
            sticky = self.sessions.get_sticky(
                user_id=user_id, ttl_s=self.flags.sticky_ttl_s
            )
            if sticky and sticky.domain in exclude:
                sticky = None

        result = self.router.route_text(text, channel=channel)
        domain, confidence = primary_span(result, exclude=exclude)
        interpreter = result.interpreter

        # 2) Barge-in: explicit marker or high-confidence non-sticky hit.
        if (
            self.flags.barge_in
            and sticky is not None
            and force_reason is None
        ):
            marker = parse_barge_marker(text)
            if marker and marker not in exclude and marker != sticky.domain:
                return ClassifyDecision(
                    domain=marker,
                    confidence=0.99,
                    interpreter=interpreter,
                    reason="barge_in",
                    sticky_session_id=sticky.id,
                    sticky_domain=sticky.domain,
                )
            barge = is_high_confidence_barge(
                result,
                sticky_domain=sticky.domain,
                min_confidence=self.flags.barge_in_min_confidence,
            )
            if barge is not None and barge[0] not in exclude:
                return ClassifyDecision(
                    domain=barge[0],
                    confidence=barge[1],
                    interpreter=interpreter,
                    reason="barge_in",
                    sticky_session_id=sticky.id,
                    sticky_domain=sticky.domain,
                )

        # 3) Stickiness: ambiguous follow-ups stay with active session.
        if (
            self.flags.stickiness
            and sticky is not None
            and sticky.domain not in exclude
            and force_reason != "not_mine_reroute"
        ):
            if is_ambiguous(result, sticky_domain=sticky.domain) or domain in {
                self.FALLBACK_DOMAIN,
                "_unfiled",
                "_ledger",
            }:
                return ClassifyDecision(
                    domain=sticky.domain,
                    confidence=confidence,
                    interpreter=interpreter,
                    reason="sticky",
                    sticky_session_id=sticky.id,
                    sticky_domain=sticky.domain,
                )

        reason = force_reason or "classify"
        return ClassifyDecision(
            domain=domain,
            confidence=confidence,
            interpreter=interpreter,
            reason=reason,
            sticky_session_id=sticky.id if sticky else None,
            sticky_domain=sticky.domain if sticky else None,
        )

    def _classify(
        self, text: str, *, channel: str
    ) -> tuple[str, float | None, str | None]:
        """Back-compat helper used by older callers/tests."""
        decision = self._decide(text, channel=channel, actor=None)
        return decision.domain, decision.confidence, decision.interpreter

    def _record_routing_correction(
        self,
        *,
        journal_id: str,
        bounced_domain: str,
        routed_domain: str,
        raw_text: str,
    ) -> tuple[str, str | None]:
        """Persist bounce as routing_correction + eval_case (+ correction_event)."""
        cid = new_ulid()
        ts = now_iso()
        wrong = {"domain": bounced_domain}
        right = {"domain": routed_domain}

        conn = connect_rw(self.ws.ledger_db)
        ce_id: int | None = None
        try:
            cur = conn.execute(
                """
                INSERT INTO correction_event (
                    entry_id, target_kind, target_id, reason_code,
                    wrong_json, right_json, applied_change_request_id, created_at
                ) VALUES (?, 'routing', ?, 'not_mine', ?, ?, NULL, ?)
                """,
                (
                    None,
                    journal_id,
                    json.dumps(wrong, separators=(",", ":")),
                    json.dumps(right, separators=(",", ":")),
                    ts,
                ),
            )
            ce_id = int(cur.lastrowid) if cur.lastrowid else None
            conn.commit()
        finally:
            conn.close()

        eval_id = append_eval_case(
            self.ws,
            source="not_mine",
            raw_text=raw_text,
            expected={"domain": routed_domain, "spans": [{"domain": routed_domain}]},
            correction_event_id=ce_id,
            context={"packs": [], "date": ts[:10], "open_hints": [], "bouncer": bounced_domain},
        )

        conn = connect_rw(self.ws.ledger_db)
        try:
            conn.execute(
                """
                INSERT INTO routing_correction (
                    id, journal_id, bounced_domain, routed_domain,
                    raw_text, reason_code, eval_case_id, created_at
                ) VALUES (?, ?, ?, ?, ?, 'not_mine', ?, ?)
                """,
                (
                    cid,
                    journal_id,
                    bounced_domain,
                    routed_domain,
                    raw_text,
                    eval_id,
                    ts,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return cid, eval_id
