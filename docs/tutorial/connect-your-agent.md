# Connect your agent

Domain Foundry is a local harness with one job: turn what you say into typed,
governed data. *How* you talk to it is up to you. Three front-ends are **tested
harnesses** — each has an automated end-to-end test in CI and a reproducible
proof snapshot:

| Harness | Best for | Install | Proof (CI test) |
|---|---|---|---|
| **[MCP](#mcp)** | Claude Desktop, Cursor, any MCP client | `pipx install domain-foundry-mcp` | `adapters/mcp/tests/test_mcp_e2e.py` |
| **[Telegram](#telegram)** | Texting a bot from your phone | `pipx install domain-foundry-telegram` | `adapters/telegram/tests/test_telegram_bridge.py` |
| **[hermes-agent](#hermes-agent)** | The hermes-agent runtime | `uv pip install -e ./adapters/hermes_agent` | `adapters/hermes_agent/tests/test_hermes_e2e.py` |

> **Tested means proven, not just present.** Each harness is driven through the
> full loop — *create a domain → capture → query → correct → review* — by an
> automated test, using the exact protocol a real client speaks. Regenerate every
> proof snapshot yourself with `python scripts/tutorial_snapshots.py`.

All three drive the **same** in-process harness and the same SQLite files. Writes
never go over HTTP (that path is intentionally disabled); a dead server can never
lose a capture.

---

## MCP

The [Model Context Protocol](https://modelcontextprotocol.io) server exposes eight
tools (`domain_foundry_capture`, `_query`, `_correct`, `_review_list`,
`_review_resolve`, `_new_domain`, `_wizard_reply`, `_health`). One server → every
MCP client.

**Install & connect Claude Desktop:**

```bash
pipx install domain-foundry-core domain-foundry-mcp
```

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

Restart Claude Desktop; the tools appear and the model uses them with
capture-first discipline. The same block works in Cursor and other MCP clients.

**Proof** — the CI test drives the server over real stdio `tools/call`, exactly as
a client does ([full snapshot](snapshots/mcp.md)):

```json
### capture
{ "status": "applied", "domain": "bouldering", "object_type": "entry", "confidence": 0.95 }
### correct
{ "action": "amend", "applied": true, "eval_case": true }
```

More: [MCP adapter README](https://github.com/finnqiao/domain_foundry/tree/main/adapters/mcp#readme).

---

## Telegram

Text a bot; the message is captured-first and routed. Corrections work by just
saying so ("actually that was a V6"). Nothing leaves your machine except the
message to Telegram itself.

**Install:**
```bash
pipx install domain-foundry-core domain-foundry-telegram
```

**Create the bot (2 minutes, all in Telegram):** message **@BotFather** → `/newbot`
→ copy the token. (Optional but recommended: message **@userinfobot** for your
numeric chat id, to keep the bot private to you.)

**Run:**
```bash
export TELEGRAM_BOT_TOKEN=<your token>
export TELEGRAM_ALLOWED_CHAT_IDS=<your chat id>   # optional — private to you
domain-foundry-telegram
```

**Proof** — the CI test runs the whole conversation through the real poller
against a mock Telegram API ([full snapshot](snapshots/telegram.md)):

```text
👤 /new track my bouldering climbing sessions
🤖 🎉 *bouldering* is live. Just text me your bouldering notes.
👤 good bouldering session at the gym, felt strong
🤖 ✅ Logged to *bouldering* (entry).
👤 actually that bouldering session felt moderate, not hard
🤖 ✏️ Corrected — and saved as a regression test.
```

> **Privacy:** this is personal data. Set `TELEGRAM_ALLOWED_CHAT_IDS` so only you
> can talk to your bot.

More: [Telegram adapter README](https://github.com/finnqiao/domain_foundry/tree/main/adapters/telegram#readme).

---

## hermes-agent

A hermes-agent plugin that registers the harness tools with capture-first
guidance, driving the in-process client (no HTTP hop).

**Install into the hermes environment** (prefer an isolated profile so your
default gateway is untouched):

```bash
hermes profile create domainfoundry --clone
HERMES_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
uv pip install --python "$HERMES_PY" -e ./adapters/hermes_agent
# enable on that profile's config.yaml:
#   plugins.enabled: [domain_foundry]
#   platform_toolsets.cli: [..., domain_foundry]
```

**Proof** — the CI test drives the adapter's own tool objects (`build_tools` over
the in-process client), the exact surface hermes-agent invokes
([full snapshot](snapshots/hermes.md)). A live end-to-end run against the
hermes-agent CLI is available via `scripts/hermes_e2e_smoke.sh`.

More: [hermes-agent adapter README](https://github.com/finnqiao/domain_foundry/tree/main/adapters/hermes_agent#readme).

---

## Anything else

Any MCP-capable runtime (including agent shells that speak MCP) connects through
the **MCP** server above with no extra work — it is the recommended path for new
integrations. Runtimes that aren't MCP-capable can call the read-only HTTP API
(`domain-foundry serve`) for queries and drive writes through the in-process
`HarnessAPI`, the same way the tested harnesses do. These paths work but are
community-supported rather than CI-gated; the three above are the tested harnesses.

## Regenerate the proofs

```bash
python scripts/tutorial_snapshots.py
# → docs/tutorial/snapshots/{cli,mcp,telegram,hermes}.md + proof.json
```

Deterministic and offline (heuristic router), so anyone gets identical snapshots.
