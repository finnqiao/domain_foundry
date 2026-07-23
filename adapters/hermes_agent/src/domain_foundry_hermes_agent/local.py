"""In-process harness client — the write path with no HTTP hop (mesh P0).

``LocalHarnessClient`` exposes the same nine methods and the same response
shapes as :class:`~domain_foundry_hermes_agent.client.DomainExpertClient`, but
embeds :class:`domain_foundry_core.api.harness.HarnessAPI` as a library and
writes straight to SQLite. A dead/absent ``domain-foundry serve`` process can
no longer block capture: "gateway down" stops being an observable state.

Requires ``domain-foundry-core`` importable in the same environment; the
plugin's client resolution falls back to HTTP when it is not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class LocalHarnessClient:
    """Same surface as DomainExpertClient, served by an embedded HarnessAPI."""

    def __init__(self, home: Path | str | None = None) -> None:
        from domain_foundry_core.api.harness import HarnessAPI
        from domain_foundry_core.paths import Workspace

        home_path = Path(home).expanduser() if home is not None else None
        Workspace(home_path).ensure_layout()
        self._api = HarnessAPI(home_path)
        self._api.init()

    # HarnessAPI holds no open connections between calls; nothing to close.
    def close(self) -> None:  # noqa: D102 — parity with DomainExpertClient
        return None

    def __enter__(self) -> LocalHarnessClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _drain(self) -> None:
        """Best-effort projection drain after a write.

        Canonical commit already happened; rendering failures stay in the
        outbox for the next drain (server loop or CLI), so errors are
        swallowed by design.
        """
        try:
            self._api.drain_projections()
        except Exception:  # noqa: BLE001
            pass

    # --------------------------------------------------------------- harness ops
    def health(self) -> dict[str, Any]:
        return self._api.health_panel()

    def capture(
        self,
        text: str,
        *,
        channel: str = "hermes-agent",
        source_ref: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        receipt = self._api.capture(
            text,
            channel=channel,
            source_ref=source_ref,
            attachments=attachments,
            actor=actor,
        )
        self._drain()
        return receipt.model_dump()

    def query(
        self,
        *,
        domain: str | None = None,
        object_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        rows = self._api.query(
            domain=domain, object_type=object_type, status=status, q=q, limit=limit
        )
        return {"rows": [r.model_dump() for r in rows]}

    def correct(
        self,
        *,
        text: str | None = None,
        entry_id: str | None = None,
        object_uid: str | None = None,
        action: str | None = None,
        fields: dict[str, Any] | None = None,
        merge_into_uid: str | None = None,
        target_domain: str | None = None,
        channel: str = "hermes-agent",
    ) -> dict[str, Any]:
        result = self._api.correct(
            text=text,
            entry_id=entry_id,
            object_uid=object_uid,
            action=action,
            fields=fields,
            merge_into_uid=merge_into_uid,
            target_domain=target_domain,
            channel=channel,
        )
        self._drain()
        return result

    def review_list(
        self,
        *,
        status: str = "pending",
        domain: str | None = None,
        include_diff: bool = False,
    ) -> dict[str, Any]:
        return {
            "items": self._api.review_list(
                status=status, domain=domain, include_diff=include_diff
            )
        }

    def review_stats(self, *, domain: str | None = None) -> dict[str, Any]:
        return self._api.review_stats(domain=domain)

    def review_resolve(
        self,
        approval_id: str,
        *,
        decision: str,
        note: str | None = None,
        resolver: str = "hermes-agent",
    ) -> dict[str, Any]:
        result = self._api.review_resolve(
            approval_id, decision=decision, note=note, resolver=resolver
        )
        self._drain()
        return result

    def new_domain(self, goal_text: str, *, test_drive: int = 5) -> dict[str, Any]:
        return self._api.new_domain(goal_text, test_drive=test_drive)

    def wizard_reply(self, session_id: str, text: str) -> dict[str, Any]:
        return self._api.wizard_reply(session_id, text)
