"""HarnessAPI — the adapter contract (plan §4.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from domain_expert_core.ledger.capture import CaptureService
from domain_expert_core.ledger.migrate import init_workspace
from domain_expert_core.ledger.models import CaptureReceipt, EntryRow, HealthReport
from domain_expert_core.paths import Workspace


class HarnessAPI:
    """
    Runtime-facing façade. Adapters translate tool calls into these methods.
    Mutating calls return receipts (PRD reliability requirement).
    """

    def __init__(self, home: Path | None = None) -> None:
        self.workspace = Workspace(home)
        self.captures = CaptureService(self.workspace)

    def init(self) -> dict[str, int]:
        return init_workspace(self.workspace.home)

    def capture(
        self,
        text: str,
        channel: str = "cli",
        source_ref: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        actor: str | None = None,
    ) -> CaptureReceipt:
        return self.captures.capture(
            text,
            channel=channel,
            source_ref=source_ref,
            attachments=attachments,
            actor=actor,
        )

    def query(
        self,
        domain: str | None = None,
        object_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> list[EntryRow]:
        return self.captures.query(
            domain=domain,
            object_type=object_type,
            status=status,
            q=q,
            limit=limit,
        )

    def health(self) -> HealthReport:
        return self.captures.health()

    # --- stubs for later phases (stable surface) ----------------------------
    def correct(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("correct() arrives in P3")

    def review_list(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise NotImplementedError("review_list() arrives in P3/P4")

    def review_resolve(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("review_resolve() arrives in P3")

    def new_domain(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("new_domain() arrives in P6")

    def wizard_reply(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("wizard_reply() arrives in P6")
