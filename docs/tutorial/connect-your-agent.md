# Connect your chat app

You already log notes in Domain Foundry. These optional front doors let you do
the same from an app you already use. Three are **proven in CI** with a
reproducible snapshot:

| Front door | Best for | Install | Proof (CI test) |
|---|---|---|---|
| **[Claude / Cursor (MCP)](#mcp)** | Chat apps that speak MCP | `pipx install domain-foundry-mcp` | `adapters/mcp/tests/test_mcp_e2e.py` |
| **[Telegram](#telegram)** | Texting a bot from your phone | `pipx install domain-foundry-telegram` | `adapters/telegram/tests/test_telegram_bridge.py` |
| **[hermes-agent](#hermes-agent)** | The hermes-agent runtime | `uv pip install -e ./adapters/hermes_agent` | `adapters/hermes_agent/tests/test_hermes_e2e.py` |

> **Proven means driven end to end** — create a passion → log → ask → correct —
> over the real protocol a client speaks. Regenerate snapshots with
> `python scripts/tutorial_snapshots.py`.

All three write to the same local data. The browser app and any HTTP adapter use
the local server (`domain-foundry serve`); if that server is down, those callers
fail visibly instead of silently.

To have the model **shape** a new passion (not just a simple log), add a key
once — `domain-foundry setup --provider deepseek -y` or **Settings** in the app.
Same key is used for Ask.

---

## MCP

The [Model Context Protocol](https://modelcontextprotocol.io) server exposes the
tools (`domain_foundry_capture`, `_query`, `_ask`, `_correct`,
`_review_list`, `_review_resolve`, `_new_domain`, `_wizard_reply`, `_health`,
plus pack install and export). One server → every MCP client.

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
🤖 Sports → climbing. Ideas: session log, ticklist…
👤 skip
🤖 *bouldering* is ready. Send a real note and we’ll file it.
👤 good bouldering session at the gym, felt strong
🤖 ✅ Logged to *bouldering* (entry).
👤 actually the rating was moderate not hard
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

Any MCP-capable runtime connects through the **MCP** server above with no extra
work — it is the recommended path for new integrations. Other runtimes can call
the local HTTP API (`domain-foundry serve`) for reads and writes, or embed the
core library while it passes the conformance suite. Those paths are
community-supported; the three above are the CI-proven ones.

## Regenerate the proofs

```bash
python scripts/tutorial_snapshots.py
# → docs/tutorial/snapshots/{cli,mcp,telegram,hermes}.md + proof.json
```

Deterministic and offline (heuristic router), so anyone gets identical snapshots.
