# Getting started

**Describe your passion. Talk to it. What you say becomes permanent, structured data you can fix later, on your machine.**

The whole loop is one conversation: you say what you already keep, you see what you could build, you pick a look, then you talk to it. Three weekends, same shape:

**[Bring the log. Pick a look.](end-to-end.html)**

1. **Bake log**: “i have a log of sourdough bakes” → options → visualize → the scatter one → ask → fix a number.
2. **Dive notebook**: animals underwater → field-guide look → build it → a sighting.
3. **Card binder**: “i collect pokemon cards” → Card dex → denser gallery → build it → Charizard files.

Do Case A yourself. The other two tabs are on the same page.

---

## Install once

Packages are not on PyPI yet. From a checkout of this repo:

```bash
git clone https://github.com/finnqiao/domain_foundry
cd domain_foundry
pip install -e .
# optional adapters: pip install -e ./adapters/mcp
domain-foundry setup
domain-foundry serve
```

Open **http://127.0.0.1:8787** if you want the little app. A key is optional: without one you still get a look you can accept.

Once the packages are on PyPI, an isolated pipx install of the core package will work. Until then, the checkout is the install.

## Talk in Claude Desktop

Install the MCP adapter from the same checkout (`pip install -e ./adapters/mcp`) if you skipped it above. In **Settings → Developer → Edit Config**, paste this and restart:

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

Then say the first line of the bake-log story:

> **You:** i have a log of sourdough bakes

Claude should relay options (chart / mix board / photos), not pick for you. If you have notebook photos, Claude OCRs them. Foundry files text; paste a notes folder path to ingest it.

> **You:** i want to data visualize all my bakes
> **Claude:** a look for the bake lab. Pick it, change it, or say build it.
> **You:** the scatter one
> **You:** which hydrations actually sprang?
> **You:** that sunday batard was 78 not 72

Same shape for the other weekends: “I want to remember the animals I see underwater,” then the field-guide look, then build it. Or “i collect pokemon cards,” then Card dex, denser gallery, build it, then a Charizard.

Cursor and other MCP clients use the same config.

## Talk in Telegram

Install the bot from the same checkout, then run it with the token from [@BotFather](https://t.me/BotFather):

```bash
pip install -e ./adapters/telegram
export TELEGRAM_BOT_TOKEN=<your token>
domain-foundry-telegram
```

Text the bot the same first line. Full token steps: [Connect your chat app](connect-your-agent.md#telegram). Hermes: same page.

## Or the terminal

```bash
domain-foundry new-domain "i have a log of sourdough bakes"
domain-foundry wizard reply <session> "i want to data visualize all my bakes"
domain-foundry wizard reply <session> "the scatter one"
domain-foundry ask "which hydrations actually sprang?"
domain-foundry correct "that sunday batard was 78 not 72"
```

Copy `<session>` from the first command’s JSON. “the scatter one” accepts the look and builds it. On the dive and card weekends, say **build it** after you like the look.

`setup --provider deepseek -y` (or `openrouter` / `anthropic`) skips the questions. Exported `DOMAIN_FOUNDRY_*` vars override the config file. See [CLI quickstart](../QUICKSTART.md).

---

## What just happened

1. **Capture first.** Your exact words are stored before anything is sorted.
2. **Looks before install.** Nothing is activated until you accept a look (or ask for a simple log).
3. **Sure, unsure, oops.** Confident notes file; the rest wait in Inbox; a one-sentence fix keeps history.
4. **Local first.** SQLite on your machine. No telemetry.

Appendices: [no-terminal notes](howto-non-technical.md) · [developer how-to](howto-technical.md) · [authoring guide](../PACK_AUTHORING.md).
