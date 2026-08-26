# Domain Foundry — Telegram bridge

**Text a bot. Get structured, permanent, correctable personal data.**

One of Domain Foundry's three **tested harnesses** (with the
[MCP server](../mcp) and the [hermes-agent adapter](../hermes_agent)). Messages
you send the bot are captured-first into your local ledger and routed to typed
domain records — and a one-message correction ("that Charizard was LP not NM")
amends the canonical record and becomes a regression test. Everything lives in local
SQLite; the only network hop is to Telegram to receive and send messages.

## What it feels like

> **You:** /new i collect pokemon cards
> **Bot:** You said “i collect pokemon cards”. You could: 3. Card dex…
> **You:** a dex of the cards i own with photos
> **Bot:** Here is a look. Reply with a number or say `build it`.
> **You:** build it
> **Bot:** *pokemon* is ready. Send a real note and we’ll file it.
> **You:** pulled a holographic Charizard from a 151 booster, NM
> **Bot:** ✅ Logged to *pokemon* (card).
> **You:** that Charizard was LP not NM
> **Bot:** ✏️ Corrected — and saved as a regression test.
> **You:** /query pokemon
> **Bot:** 📚 *pokemon* — 1 shown: • pulled a holographic Charizard…

## Install

```bash
pip install -e ./adapters/telegram        # from a checkout
# published:  pipx install domain-foundry-telegram
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
looks → `build it` → capture → correction → `/query` → `/review` — through the
real poller against an in-memory mock Telegram API, offline and deterministic
(no token needed). It is part of CI and regenerates the tutorial's Telegram
proof snapshot. The only piece that needs a live token is the final
over-the-wire hop, which the mock stands in for byte-for-byte.
