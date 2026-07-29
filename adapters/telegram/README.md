# Domain Foundry — Telegram bridge

**Text a bot. Get structured, permanent, correctable personal data.**

One of Domain Foundry's three **tested harnesses** (with the
[MCP server](../mcp) and the [hermes-agent adapter](../hermes_agent)). Messages
you send the bot are captured-first into your local ledger and routed to typed
domain records — and a one-message correction ("actually that was a V6") amends
the canonical record and becomes a regression test. Everything lives in local
SQLite; the only network hop is to Telegram to receive and send messages.

## What it feels like

> **You:** /new track my bouldering sessions
> **Bot:** 🎉 *bouldering* is live. Just text me your bouldering notes.
> **You:** sent a tough V5 on the overhang today, crux was the heel hook
> **Bot:** ✅ Logged to *bouldering* (entry).
> **You:** actually that felt more moderate than hard
> **Bot:** ✏️ Corrected — and saved as a regression test.
> **You:** /query bouldering
> **Bot:** 📚 *bouldering* — 1 shown: • sent a tough V5 on the overhang…

## Install

```bash
pipx install domain-foundry-telegram      # or: pip install domain-foundry-telegram
# from a checkout:  pip install -e ./adapters/telegram
```

## Create your bot (2 minutes, all in the Telegram app)

1. Open Telegram and message **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`, pick a name and a username. BotFather replies with a **token**
   like `123456789:AAExampleTokenABCdef`.
3. (Recommended, keeps it private) message **[@userinfobot](https://t.me/userinfobot)**
   to get **your numeric chat id**.

## Run

```bash
export TELEGRAM_BOT_TOKEN=123456789:AAExampleTokenABCdef
export DOMAIN_FOUNDRY_HOME=~/.domain_foundry            # optional
export TELEGRAM_ALLOWED_CHAT_IDS=<your chat id>         # optional but recommended — private to you
domain-foundry-telegram
```

Now open your bot in Telegram and text it. Commands: plain text captures; `/new
<goal>` creates a domain; `/query <domain>` lists records; `/review` shows the
queue; `/help`.

| Setting | Env | Default |
|---|---|---|
| bot token (required) | `TELEGRAM_BOT_TOKEN` | — |
| workspace home | `DOMAIN_FOUNDRY_HOME` | `~/.domain_foundry` |
| private allowlist | `TELEGRAM_ALLOWED_CHAT_IDS` | open (any chat) |
| API base (for testing) | `TELEGRAM_API_BASE` | `https://api.telegram.org` |

> **Privacy:** this is personal data. Set `TELEGRAM_ALLOWED_CHAT_IDS` to your own
> chat id so only you can talk to the bot. Without it, anyone who finds the bot
> can capture into your ledger.

## Proven end-to-end

`tests/test_telegram_bridge.py` runs the **entire conversation loop** — `/new` →
capture → correction → `/query` → `/review` — through the real poller against an
in-memory mock Telegram API, offline and deterministic (no token needed). It is
part of CI and regenerates the tutorial's Telegram proof snapshot. The only piece
that needs a live token is the final over-the-wire hop, which the mock stands in
for byte-for-byte.
