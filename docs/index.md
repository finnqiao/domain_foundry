# Domain Foundry

**Describe your passion. Get an app. Talk to it.**

**Domain Foundry** turns what you say into neat, correctable notes for the things
you care about — and keeps them on your own computer.

> Say what happened. See it filed. Fix a mistake in one sentence. It stays local.

!!! note "Name"
    Provisional public name: **Domain Foundry** (`domain-foundry-core` /
    CLI `domain-foundry`). PyPI / GitHub / trademark availability before publish
    is still a human gate — see [ADR-005](adr/ADR-005-name-decision.md).

## What you get

1. **Write it down first** — your exact words are saved before anything is sorted.
2. **Never lose a note** — if it isn't sure where something belongs, it waits in Inbox.
3. **Fix it in one sentence** — say so in plain language; history is preserved.
4. **Your passion, your app** — describe an interest; get a place to log and browse it.
5. **Local first** — data lives on your machine; no telemetry.
6. **Gets better when you correct it** — each fix teaches it for next time.

## Where to start

<div class="grid cards" markdown>

- :material-rocket-launch: **[Getting started](tutorial/getting-started.md)**

    Two tracks: talk to it in an app, or use the CLI.

- :material-hand-heart: **[No terminal](tutorial/howto-non-technical.md)**

    Install once, then use Claude, Telegram, or the browser.

- :material-book-open-page-variant: **[Turn a hobby into an app](tutorial/end-to-end.html)**

    Story plus a click-through tutorial — everyone and the terminal.

- :material-console: **[Quickstart (CLI)](QUICKSTART.md)**

    Clean machine to a logged note in minutes.

- :material-connection: **[Connect your chat app](tutorial/connect-your-agent.md)**

    Claude Desktop, Cursor, Telegram, and hermes-agent.

- :material-shield-lock: **[Security](security.md)**

    Local binding, token auth, path safety.

</div>

## Under the hood (for builders)

- **Python core** (`domain-foundry-core`) — storage, routing, corrections, views.
- **Local server** — `domain-foundry serve` hosts the app and the shared API.
- **React app shell** — remixable blocks driven by passion definitions.
- **SQLite × 2** — append-only history + typed records on disk.
- **Adapters** — Claude/Cursor (MCP), Telegram, hermes-agent (each proven in CI).

Builder deep-dives: [Concepts](concepts/index.md) · [Architecture](architecture.md) ·
[Pack authoring](PACK_AUTHORING.md).

## License

MIT. See the repository `LICENSE`.
