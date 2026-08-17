"""FastMCP server exposing the Domain Foundry harness as MCP tools.

The tools mirror the CLI and the hermes-agent adapter surface so behaviour is
identical across every front-end. Writes go straight to SQLite via an embedded
``HarnessAPI`` — a dead or absent ``domain-foundry serve`` can never block a
capture, and there is no HTTP hop for a client on the same machine.

Home resolution: ``--home`` CLI flag > ``DOMAIN_FOUNDRY_HOME`` env > the default
``~/.domain_foundry``. Everything is local; no telemetry, no network calls.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

CAPTURE_FIRST_GUIDANCE = (
    "Capture first: send the user's raw words to domain_foundry_capture before "
    "you interpret them. The harness stores the message verbatim, then routes it "
    "to a typed domain record (or a review card when unsure). Never paraphrase a "
    "capture into a summary — preserve the exact words. To answer questions about "
    "what they logged, call domain_foundry_ask (grounded, read-only). To fix a "
    "mistake, call domain_foundry_correct with a plain-language correction; the "
    "canonical record is amended and the change becomes a permanent regression test."
)


class _Harness:
    """Thin in-process wrapper around HarnessAPI (self-contained, no HTTP)."""

    def __init__(self, home: Path | str | None = None) -> None:
        from domain_foundry_core.api.harness import HarnessAPI
        from domain_foundry_core.paths import Workspace

        home_path = Path(home).expanduser() if home is not None else None
        Workspace(home_path).ensure_layout()
        self.api = HarnessAPI(home_path)
        self.api.init()

    def _drain(self) -> None:
        try:
            self.api.drain_projections()
        except Exception:  # noqa: BLE001 — canonical commit already durable
            pass


def build_server(home: Path | str | None = None) -> FastMCP:
    """Build a FastMCP server bound to a Domain Foundry home."""
    harness = _Harness(home)
    api = harness.api
    mcp = FastMCP("domain-foundry", instructions=CAPTURE_FIRST_GUIDANCE)

    @mcp.tool()
    def domain_foundry_capture(
        text: str, channel: str = "mcp", source_ref: str | None = None
    ) -> dict[str, Any]:
        """Capture a raw message into the ledger, then route it to a domain.

        This is the primary tool. Pass the user's words verbatim. Returns a
        receipt with the routing decision (domain, object_type, confidence,
        disposition) and status (applied / review / unfiled). Nothing is ever
        dropped: uncertain captures become a review card or an unfiled card.
        """
        receipt = api.capture(text, channel=channel, source_ref=source_ref)
        harness._drain()
        return receipt.model_dump()

    @mcp.tool()
    def domain_foundry_query(
        domain: str | None = None,
        object_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Read canonical records (read-only). Filter by domain / object_type /
        status, or full-text search with ``q``. Returns typed rows with their
        provenance back to the original capture."""
        rows = api.query(
            domain=domain, object_type=object_type, status=status, q=q, limit=limit
        )
        return {"rows": [r.model_dump() for r in rows]}

    @mcp.tool()
    def domain_foundry_ask(
        question: str, domain: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        """Answer a question using only the user's captured records.

        Read-only. Prefer this when the user asks "what did I…", "when was my
        last…", or similar. Answers cite the records they used. Use query when
        you need the raw rows instead of a grounded answer.
        """
        return api.ask(question, domain=domain, limit=limit)

    @mcp.tool()
    def domain_foundry_correct(
        text: str | None = None,
        entry_id: str | None = None,
        action: str | None = None,
        target_domain: str | None = None,
    ) -> dict[str, Any]:
        """Apply a one-message correction (e.g. "no, that was a V6 not a V5").

        Amends the canonical record while preserving full history; the fix is
        compiled into a replayable eval case. Optionally target a specific
        ``entry_id`` or force an ``action`` (amend|move|merge|undo|mark_wrong)."""
        result = api.correct(
            text=text, entry_id=entry_id, action=action, target_domain=target_domain
        )
        harness._drain()
        return result

    @mcp.tool()
    def domain_foundry_review_list(
        status: str = "pending", domain: str | None = None
    ) -> dict[str, Any]:
        """List items in the approval queue (captures the harness was unsure
        about, or high-impact ops). Resolve with domain_foundry_review_resolve."""
        return {"items": api.review_list(status=status, domain=domain)}

    @mcp.tool()
    def domain_foundry_review_resolve(
        approval_id: str, decision: str, note: str | None = None
    ) -> dict[str, Any]:
        """Approve or deny a queued item. ``decision`` is approved|denied|expired."""
        result = api.review_resolve(approval_id, decision=decision, note=note)
        harness._drain()
        return result

    @mcp.tool()
    def domain_foundry_new_domain(goal: str, test_drive: int = 5) -> dict[str, Any]:
        """Start the idea-atlas wizard. Returns a neighborhood (refine / expand /
        idea cards) and a session id — never an installed pack. Continue with
        domain_foundry_wizard_reply until the user commits an idea. Do not pick
        for them."""
        return api.new_domain(goal, test_drive=test_drive)

    @mcp.tool()
    def domain_foundry_wizard_reply(session_id: str, text: str) -> dict[str, Any]:
        """Send one reply to an open wizard session (pick an idea, refine a
        topic, 'just a simple log', 'show schema', or 'skip')."""
        return api.wizard_reply(session_id, text)

    @mcp.tool()
    def domain_foundry_atlas_search(goal: str, cursor_id: str | None = None) -> dict[str, Any]:
        """Search the idea atlas. Returns breadcrumb, refine children, expand
        neighbors, and app ideas (world + foundry) for the matched neighborhood."""
        return api.atlas_search(goal, cursor_id=cursor_id)

    @mcp.tool()
    def domain_foundry_inspect_pack(name: str) -> dict[str, Any]:
        """Read an installed (or bundled) pack's YAML files without changing it."""
        return api.inspect_pack(name)

    @mcp.tool()
    def domain_foundry_suggest(domain: str) -> dict[str, Any]:
        """Neighbor-idea or hardening suggestion from recent captures in a domain."""
        return {"suggestion": api.wizard_suggest(domain)}

    @mcp.tool()
    def domain_foundry_apply_pack_edit(
        domain: str, text: str, confirm: bool = False
    ) -> dict[str, Any]:
        """Preview a natural-language pack edit. Pass confirm=true to apply
        (writes a migration). Always preview first."""
        return api.apply_pack_edit(domain, text, confirm=confirm)

    @mcp.tool()
    def domain_foundry_health() -> dict[str, Any]:
        """Integrity + FK checks, entry counts, and today's LLM spend."""
        return api.health_panel()

    @mcp.tool()
    def domain_foundry_activate_pack(name: str) -> dict[str, Any]:
        """Install a bundled Domain Pack so captures can route to it."""
        result = api.activate_pack(name)
        harness._drain()
        return result

    @mcp.tool()
    def domain_foundry_export(domain: str | None = None) -> dict[str, Any]:
        """Export canonical objects as secrets-free JSON."""
        return api.export_data(domain=domain)

    return mcp


def main() -> None:
    """Console entry point: run the stdio MCP server (what clients launch)."""
    parser = argparse.ArgumentParser(prog="domain-foundry-mcp")
    parser.add_argument(
        "--home",
        default=os.environ.get("DOMAIN_FOUNDRY_HOME"),
        help="Workspace root (default: $DOMAIN_FOUNDRY_HOME or ~/.domain_foundry)",
    )
    args = parser.parse_args()
    server = build_server(args.home)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
