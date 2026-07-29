"""Domain Foundry MCP server.

Exposes the Domain Foundry harness (capture-first ledger, hybrid routing,
policy-gated apply, one-message corrections, guided domain wizard) as
Model Context Protocol tools, so any MCP client — Claude Desktop, Cursor, or a
custom agent runtime — can drive the same local-first SQLite substrate that the
CLI and the hermes-agent adapter use.

Writes run **in-process** against ``HarnessAPI`` (the harness's HTTP write path
is intentionally 410 Gone); nothing is proxied over the network.
"""

from __future__ import annotations

from domain_foundry_mcp.server import build_server, main

__all__ = ["build_server", "main"]
__version__ = "0.1.0"
