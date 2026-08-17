# Use Domain Foundry (the no-terminal guide)

**What it is, in one line:** you say what you did — in a chat — and it remembers it
forever as neat, organized, correctable notes on your own computer.

No spreadsheets. No forms. No "sync." You talk; it files.

> **The 20-second version**
>
> 1. Install it once (one line — ask a techy friend or paste it yourself).
> 2. Talk to it in **Claude Desktop** or a **Telegram bot**.
> 3. To fix something, just say so: *"actually the rating was moderate not hard."*

---

## Pick how you want to talk to it

You only need **one** of these. All three keep your data in one place on your
computer.

### 🗨️ Option A — Claude Desktop (easiest if you already use Claude)

1. Install the Claude Desktop app.
2. One-time setup: open **Settings → Developer → Edit Config** and paste this,
   then restart Claude:
   ```json
   {
     "mcpServers": {
       "domain-foundry": { "command": "domain-foundry-mcp", "args": ["--home", "~/.domain_foundry"] }
     }
   }
   ```
   *(If `domain-foundry-mcp` isn't found, it needs a one-line install first — see
   [Getting started](getting-started.md). This is the only techy bit.)*
3. Now just chat:
   > **You:** track my houseplants
   > **You:** watered the monstera, new leaf coming in
   > **You:** actually it was the fiddle-leaf, not the monstera

### 📱 Option B — A Telegram bot you text

1. In Telegram, message **@BotFather**, send `/newbot`, pick a name. It gives you
   a code (a "token").
2. Someone starts the bot once with that token (one line — see
   [Getting started](getting-started.md)).
3. Open your bot and text it like a friend who never forgets:
   > **You:** /new track my coffee
   > **You:** V60 with the Ethiopian, tasted like blueberry
   > **You:** /query coffee   ← ask what you've logged

### Option C — Pull in notes you already have (a few clicks)

Already keep notes in a folder (Apple Notes export, Obsidian, plain text files)?

1. Open **http://127.0.0.1:8787** in your browser (after someone runs
   `domain-foundry serve` — one line).
2. Click **Settings** → **Sources**.
3. Type the folder, click **Preview routing** — it shows where your notes *would*
   go, and **changes nothing**.
4. Happy with it? Click **Pull in**.

![Add a source, inside Settings: paste a folder, preview where notes land, pull in](snapshots/img/spa_sources.png)

Your original notes are never moved, renamed, or edited — this only *copies* the
words into your foundry.

---

## The three things worth knowing

**1. It never guesses wildly.** If it's sure where a note belongs, it files it. If
it isn't, it keeps the note aside as "unfiled" for you to sort later. It never
throws anything away.

**2. Fixing a mistake is one sentence.** Say *"no, that was Tuesday"* or *"actually
it was a V6"* and it corrects the record — and remembers so it won't make that
mistake again.

**3. It's all yours.** Everything lives in a file on your computer. Nothing is
uploaded, and there's no account to sign up for. You can walk away anytime and the
data is just… there.

---

## Little things you'll want

- **Keep your Telegram bot private.** When it's set up, add your own chat ID so
  only you can talk to it (your helper will know how, or see the
  [Telegram guide](connect-your-agent.md#telegram)).
- **"Where did my note go?"** In Claude Desktop, ask *"what have I logged in
  coffee?"* In Telegram, send `/query coffee`. In the browser app
  (http://127.0.0.1:8787), click the domain on the left.
- **Start small.** Track one thing you actually do — coffee, runs, plants, books.
  Add more foundries whenever you like by saying *"track my …"*.
- **Want it to understand how you talk?** Add a key in **Settings**. Without one
  you still get a simple log you can talk to; with one, describing a passion
  picks fields that match how you actually speak (and you can still say
  `rating = 9` to fix a number).

That's the whole thing. Talk to it, and it remembers — accurately, forever, and
only for you. The same loop as a page you can click through:
**[Turn a hobby into an app](end-to-end.html#tutorial)** (pick **Everyone**).
When you want the technical details, see the
[developer guide](howto-technical.md).
