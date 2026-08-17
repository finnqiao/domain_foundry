"""Domain Foundry MCP server.

Exposes the Domain Foundry harness (capture-first ledger, hybrid routing,
policy-gated apply, one-message corrections, guided domain wizard) as
Model Context Protocol tools, so any MCP client — Claude Desktop, Cursor, or a
custom agent runtime — can drive the same local-first SQLite substrate that the
CLI and the hermes-agent adapter use.

This adapter embeds ``HarnessAPI`` in-process (no network hop). The same
operations are also served over HTTP by ``domain-foundry serve`` (ADR-006);
in-process embedding stays legal only while this adapter passes the Gate-1
conformance suite (docs/build-plan-2026-08/02-SLICE-1-ACTIVATION.md).
"""

from __future__ import annotations

from domain_foundry_mcp.server import build_server, main

__all__ = ["build_server", "main"]
__version__ = "0.1.0"
