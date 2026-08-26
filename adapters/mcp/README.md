# Domain Foundry — MCP server

**Talk to your Domain Foundry from Claude Desktop, Cursor, or any MCP client.**

This is one of Domain Foundry's three **tested harnesses** (alongside the
[hermes-agent adapter](../hermes_agent) and the [Telegram bridge](../telegram)).
It exposes the harness over the [Model Context Protocol](https://modelcontextprotocol.io),
so any MCP-capable agent drives the *same* local-first SQLite substrate as the
CLI — capture-first ledger, hybrid routing, policy-gated apply, one-message
corrections, and the guided domain wizard.

This adapter embeds `HarnessAPI` in-process (no network hop), while
`domain-foundry serve` exposes the same read/write contract over HTTP. There is
no telemetry.

## Tools

| MCP tool | What it does |
|---|---|
| `domain_foundry_capture` | Store a raw message, then route it to a typed domain record |
| `domain_foundry_query` | Read canonical records (filter / full-text search) |
| `domain_foundry_ask` | Answer a question using only captured records |
| `domain_foundry_correct` | One-message correction → amends the record, becomes an eval case |
| `domain_foundry_review_list` / `_resolve` | See and clear the approval queue |
| `domain_foundry_new_domain` / `domain_foundry_wizard_reply` | Idea options, then HTML looks; wait until the user accepts a look |
| `domain_foundry_atlas_search` | Browse buckets → practices → ideas without installing |
| `domain_foundry_inspect_pack` | Read pack YAML |
| `domain_foundry_suggest` | Neighbor-idea / hardening suggestion from captures |
| `domain_foundry_apply_pack_edit` | Preview (or confirm) a natural-language pack edit |
| `domain_foundry_activate_pack` | Install a bundled analog pack for deterministic routing |
| `domain_foundry_export` | Export canonical objects as secrets-free JSON |
| `domain_foundry_health` | Integrity checks, counts, today's LLM spend |

## Install

```bash
pip install -e ./adapters/mcp          # from a checkout
# published:  pipx install domain-foundry-mcp
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

> **You:** i collect pokemon cards
> **Claude:** *(calls `domain_foundry_new_domain`)* Card dex is one of the ideas. Nothing is live yet.
> **You:** a dex of the cards i own with photos
> **Claude:** *(calls `domain_foundry_wizard_reply`)* Here's a look. Say `build it` when you like it.
> **You:** build it
> **Claude:** *(calls `domain_foundry_wizard_reply`)* **pokemon** is ready.
> **You:** pulled a holographic Charizard from a 151 booster, NM
> **Claude:** *(calls `domain_foundry_capture`)* Logged to **pokemon** ✓
> **You:** that Charizard was LP not NM
> **Claude:** *(calls `domain_foundry_correct`)* Corrected — and saved as a regression test.

(A full copy-paste config is in [`claude_desktop_config.example.json`](./claude_desktop_config.example.json).
The same `command`/`args` block works in Cursor and other MCP clients.)

## Configure

| Setting | Source | Default |
|---|---|---|
| workspace home | `--home` arg, then `DOMAIN_FOUNDRY_HOME` | `~/.domain_foundry` |

## Proven end-to-end

`tests/test_mcp_e2e.py` launches this server over stdio exactly as a client does,
then drives the core loop — **looks → build it → capture → query → correct →
review → health** — and asserts the Gate 1 tools are advertised. The full Gate 1
conformance journey additionally exercises export and restart through the real
stdio subprocess in `tests/conformance`.
