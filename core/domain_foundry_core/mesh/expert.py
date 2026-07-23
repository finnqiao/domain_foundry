"""Domain Expert runner skeleton — dequeue → in-process HarnessAPI → reply."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.mesh.inbox import DomainInbox, InboxMessage
from domain_foundry_core.mesh.outbound import OutboundMessage, OutboundQueue
from domain_foundry_core.paths import Workspace

# Optional hook for tests / busy simulation: (domain, msg) -> None
ProcessHook = Callable[[str, InboxMessage], dict[str, Any] | None]


@dataclass
class ExpertStats:
    domain: str
    processed: int = 0
    failed: int = 0
    last_msg_id: str | None = None
    last_error: str | None = None
    last_outbound_id: str | None = None


@dataclass
class ExpertRunner:
    """Serial-within-domain Expert loop.

    One runner owns one domain and processes its inbox in order. Multiple
    runners for different domains may run concurrently (invariant §8.4).
    """

    domain: str
    workspace: Workspace | None = None
    poll_interval_s: float = 0.05
    process_hook: ProcessHook | None = None
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _busy: threading.Lock = field(default_factory=threading.Lock, init=False)
    stats: ExpertStats = field(init=False)

    def __post_init__(self) -> None:
        self.ws = self.workspace or Workspace()
        self.inbox = DomainInbox(self.ws)
        self.outbound = OutboundQueue(self.ws)
        self.harness = HarnessAPI(self.ws.home)
        self.stats = ExpertStats(domain=self.domain)

    def enqueue_reply(
        self,
        *,
        text: str,
        channel: str,
        destination: str,
        payload: dict[str, Any] | None = None,
    ) -> OutboundMessage:
        """Enqueue an origin-tagged reply for gateway delivery."""
        return self.outbound.enqueue(
            origin_domain=self.domain,
            text=text,
            channel=channel,
            destination=destination,
            payload=payload,
        )

    def process_one(self) -> InboxMessage | None:
        """Claim and process at most one message. Serial via `_busy` lock."""
        with self._busy:
            msg = self.inbox.claim_next(self.domain)
            if msg is None:
                return None
            try:
                reply = self._handle(msg)
                self.inbox.ack(msg.id, reply=reply)
                outbound_id = self._maybe_enqueue_reply(msg, reply)
                self.stats.processed += 1
                self.stats.last_msg_id = msg.id
                self.stats.last_error = None
                self.stats.last_outbound_id = outbound_id
            except Exception as exc:  # noqa: BLE001
                self.inbox.fail(msg.id, str(exc))
                self.stats.failed += 1
                self.stats.last_msg_id = msg.id
                self.stats.last_error = str(exc)
                raise
            return msg

    def _maybe_enqueue_reply(
        self, msg: InboxMessage, reply: dict[str, Any]
    ) -> str | None:
        """If the handler returned outbound_text/reply_text, enqueue it."""
        text = reply.get("outbound_text") or reply.get("reply_text")
        if not text:
            return None
        channel = str(
            reply.get("channel")
            or msg.payload.get("channel")
            or "cli"
        )
        destination = str(
            reply.get("destination")
            or msg.payload.get("destination")
            or msg.payload.get("actor")
            or msg.payload.get("source_ref")
            or "unknown"
        )
        out = self.enqueue_reply(
            text=str(text),
            channel=channel,
            destination=destination,
            payload={"inbox_id": msg.id, "journal_id": msg.journal_id},
        )
        return out.id

    def drain(self, *, max_n: int = 100) -> int:
        """Process up to max_n pending messages serially."""
        n = 0
        while n < max_n:
            if self.process_one() is None:
                break
            n += 1
        return n

    def run_forever(self) -> None:
        """Blocking poll loop until stop() is called."""
        self._stop.clear()
        while not self._stop.is_set():
            processed = self.process_one()
            if processed is None:
                self._stop.wait(self.poll_interval_s)

    def stop(self) -> None:
        self._stop.set()

    def _handle(self, msg: InboxMessage) -> dict[str, Any]:
        if self.process_hook is not None:
            hooked = self.process_hook(self.domain, msg)
            if hooked is not None:
                return hooked

        text = str(msg.payload.get("text") or "")
        channel = str(msg.payload.get("channel") or "mesh")
        source_ref = msg.payload.get("source_ref")
        # Prefer mesh-scoped idempotency so channel redelivery + journal
        # redelivery both collapse onto one harness capture.
        mesh_ref = f"mesh:{msg.journal_id}"
        receipt = self.harness.capture(
            text,
            channel=channel,
            source_ref=str(source_ref) if source_ref else mesh_ref,
            actor=msg.payload.get("actor"),
        )
        return {
            "entry_id": receipt.entry_id,
            "capture_event_id": receipt.capture_event_id,
            "status": receipt.status,
            "domain": self.domain,
            "idempotent_replay": receipt.idempotent_replay,
        }
