# Getting started

**Describe your passion. Talk to it. It becomes permanent, structured, correctable data — on your machine, in plain SQLite.**

You don't fill in forms. You say what happened in your own words — in Claude
Desktop, in a Telegram chat, or on the command line — and Domain Foundry captures
it, files it into a typed record, and lets you fix any mistake in one sentence.

Here is a real capture feed after five messages about bouldering. Notice the
routing badges: confident captures are **applied**; ones it isn't sure about are
kept as an **unfiled** card instead of being guessed at or dropped. Every row has
a **Wrong?** button — one tap to correct it.

![Domain Foundry capture feed — messages routed to a bouldering domain with confidence badges](snapshots/img/capture_feed.png)

Pick your track. Both reach the same local data.

---

## Track A — For everyone (no terminal after install)

One install, then you never touch a terminal again: you talk to Domain Foundry
inside an app you already use.

### Option 1 — Claude Desktop (or Cursor, or any MCP client)

1. **Install once** (copy-paste this line):
   ```bash
   pipx install domain-foundry-core domain-foundry-mcp
   ```
2. In **Claude Desktop → Settings → Developer → Edit Config**, paste:
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
3. Restart Claude Desktop. Now just talk:

   > **You:** track my bouldering sessions
   > **Claude:** Your *bouldering* domain is live.
   > **You:** sent a tough V5 on the overhang today, crux was the heel hook
   > **Claude:** Logged to **bouldering** ✓
   > **You:** actually that felt more moderate than hard
   > **Claude:** Corrected — and saved as a regression test.

That's it. The same config block works in Cursor and other MCP clients. Full
details: [Connect your agent → MCP](connect-your-agent.md#mcp).

### Option 2 — A Telegram bot you text

1. **Install once:**
   ```bash
   pipx install domain-foundry-core domain-foundry-telegram
   ```
2. In Telegram, message **@BotFather**, send `/newbot`, and copy the token.
3. **Start it** (once):
   ```bash
   export TELEGRAM_BOT_TOKEN=<your token>
   domain-foundry-telegram
   ```
4. Open your bot and text it like a friend who never forgets:

   > **You:** /new track my coffee brews
   > **You:** V60 with the Ethiopian, 15g in, tasted like blueberry
   > **Bot:** ✅ Logged to *coffee*.

Full details, including how to keep the bot private to you:
[Connect your agent → Telegram](connect-your-agent.md#telegram).

---

## Track B — For developers (the CLI)

```bash
pipx install domain-foundry-core        # or: pip install -e . from a checkout
domain-foundry setup                    # bring your own key, then pick a starting point

# describe a passion → get a working domain (no code)
domain-foundry new-domain "track my bouldering climbing sessions" --reply skip

# talk to it
domain-foundry capture "good bouldering session at the gym, felt strong"
domain-foundry query --domain bouldering
domain-foundry correct "actually that felt more moderate than hard"

# see it in a browser (the screenshot above)
domain-foundry serve   # → http://127.0.0.1:8787
```

`setup` runs `init` for you and ends by asking where you want to start. Already
have opinions? `domain-foundry setup --provider anthropic -y` skips every
question, and exported `DOMAIN_FOUNDRY_*` vars override it entirely — see
[Bring your own key](../QUICKSTART.md#bring-your-own-key) for the tier split and
the resolution order.

Author your own richer domains (schema, routing rules, projections) in the
[Pack authoring guide](../PACK_AUTHORING.md); remix an example in an afternoon
with the [plant-care tutorial](../tutorial-plant-care.md).

---

## What just happened

1. **Capture first.** Your exact words are stored in an append-only ledger
   *before* anything interprets them. Nothing is ever silently dropped.
2. **Routed, not guessed.** A record is created only when the system is
   confident; otherwise it waits as a review or unfiled card.
3. **One-message corrections.** A plain-language fix amends the canonical record,
   preserves history, and compiles into a replayable regression test — so the
   system provably improves.
4. **Local first.** Everything lives in SQLite on your machine. No telemetry, no
   cloud, no vector soup — files you can open with any SQLite browser.

Next: **[Connect your agent](connect-your-agent.md)** — the three tested harnesses
(MCP, Telegram, hermes-agent), each with a copy-paste setup and a proof snapshot.

Already have a setup? **[Bolt it on](adopt-in-place.md)** — install alongside,
pull your existing notes and logs into foundries (read-only, idempotent), and add
it to your current Hermes without rewriting anything.
