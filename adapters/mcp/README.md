# Domain Foundry — MCP server

**Talk to your Domain Foundry from Claude Desktop, Cursor, or any MCP client.**

This is one of Domain Foundry's three **tested harnesses** (alongside the
[hermes-agent adapter](../hermes_agent) and the [Telegram bridge](../telegram)).
It exposes the harness over the [Model Context Protocol](https://modelcontextprotocol.io),
so any MCP-capable agent drives the *same* local-first SQLite substrate as the
CLI — capture-first ledger, hybrid routing, policy-gated apply, one-message
corrections, and the guided domain wizard.

Writes run **in-process** against `HarnessAPI` (the harness's HTTP write path is
intentionally `410 Gone`). Nothing is proxied over the network; there is no
telemetry.

## Tools

| MCP tool | What it does |
|---|---|
| `domain_foundry_capture` | Store a raw message, then route it to a typed domain record |
| `domain_foundry_query` | Read canonical records (filter / full-text search) |
| `domain_foundry_correct` | One-message correction → amends the record, becomes an eval case |
| `domain_foundry_review_list` / `_resolve` | See and clear the approval queue |
| `domain_foundry_new_domain` / `domain_foundry_wizard_reply` | Guided wizard: describe a passion → get a working domain |
| `domain_foundry_health` | Integrity checks, counts, today's LLM spend |

## Install

```bash
pipx install domain-foundry-mcp        # or: pip install domain-foundry-mcp
# from a checkout:  pip install -e ./adapters/mcp
```

This puts a `domain-foundry-mcp` command on your PATH — the stdio server that MCP
clients launch.

## Connect Claude Desktop (2 minutes, no terminal after install)

Open **Settings → Developer → Edit Config** and add:

```json
{
  "mcpServers": {
    "domain-foundry": {
      "command": "domain-foundry-mcp",
      "args": ["--home", "~/.domain_foundry"]
    }
  }
}
```

Restart Claude Desktop. You'll see the Domain Foundry tools appear. Now just talk:

> **You:** track my bouldering sessions
> **Claude:** *(calls `domain_foundry_new_domain` → `domain_foundry_wizard_reply`)* Your bouldering domain is live.
> **You:** sent a tough V5 on the overhang today, crux was the heel hook
> **Claude:** *(calls `domain_foundry_capture`)* Logged to **bouldering** ✓
> **You:** actually that felt more moderate than hard
> **Claude:** *(calls `domain_foundry_correct`)* Corrected — and saved as a regression test.

(A full copy-paste config is in [`claude_desktop_config.example.json`](./claude_desktop_config.example.json).
The same `command`/`args` block works in Cursor and other MCP clients.)

## Configure

| Setting | Source | Default |
|---|---|---|
| workspace home | `--home` arg, then `DOMAIN_FOUNDRY_HOME` | `~/.domain_foundry` |

## Proven end-to-end

`tests/test_mcp_e2e.py` launches this server over stdio exactly as a client does,
then drives the full loop — **wizard → capture → query → correct → review →
health** — asserting each step. This is the harness's MCP contract; it is part of
CI and regenerates the tutorial's MCP proof snapshot.
