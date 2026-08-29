# Domain Foundry

**Turn an interest into an evidence-backed app you own.**

**Domain Foundry** researches the real practice, compares three materially
different concepts, derives a workload-fit schema and domain-specific
experience, and compiles the selected product into a local app with its evidence
and build receipt.

> One inspectable specification from evidence to owned application.

!!! note "Name"
    Provisional public name: **Domain Foundry** (`domain-foundry-core` /
    CLI `domain-foundry`). PyPI currently has no public projects at the proposed
    names, but those names are not reserved; the `Domain-Foundry` GitHub
    organization is occupied. A live US application for the exact mark covers
    directly overlapping software services, so the current name is
    release-blocked pending rename, rights agreement, or qualified clearance.
    See [ADR-005](adr/ADR-005-name-decision.md).

## What you get

1. **Research before generation** with licensed, reviewable evidence.
2. **Choose among structural product alternatives**, not color variants.
3. **Derive the model from identities, lifecycles, time, and named workloads.**
4. **Compile preview and owned app from one strict `FoundrySpec`.**
5. **Keep data, evidence, schema, and export local and inspectable.**
6. **Release against independent task, accessibility, security, and build gates.**

## Where to start

<div class="grid cards" markdown>

- :material-anvil: **[Foundry redesign](FOUNDRY_REDESIGN.md)**

    See the end-to-end compiler path, three exact apps, knowledge fabric, and
    honest release gates.

- :material-source-fork: **[AI remix landscape](remix-landscape.md)**

    Sekai, Rosebud, Lovable, Replit, Bolt, Base44, v0, Websim, Magic Patterns,
    Onlook, and Dyad, compared by what “remix” actually preserves.

- :material-book-open-page-variant: **[Bring the log. Pick a look.](tutorial/end-to-end.html)**

    One conversation, three weekends: a bake log you already have, animals you
    want to remember, and a binder of cards.

- :material-rocket-launch: **[Getting started](tutorial/getting-started.md)**

    Install from this checkout, then say the first line.

- :material-console: **[Quickstart (CLI)](QUICKSTART.md)**

    The same weekend from the terminal, then builder extras.

- :material-connection: **[Connect your chat app](tutorial/connect-your-agent.md)**

    Claude Desktop, Cursor, Telegram, and hermes-agent.

- :material-hand-heart: **[No-terminal notes](tutorial/howto-non-technical.md)**

    Install once, then stay in the chat you already use.

- :material-shield-lock: **[Security](security.md)**

    Local binding, model/search boundaries, generated-app CSP, and path safety.

</div>

## Under the hood (for builders)

- **Python core** (`domain-foundry-core`): storage, filing, corrections, views.
- **FoundrySpec compiler**: evidence, product alternatives, workload-derived
  schema, domain experience, exact owned app, and proof receipt.
- **Local server**: `domain-foundry serve` hosts the app and the shared API.
- **React app shell**: remixable blocks driven by the interest you just built.
- **SQLite × 2**: append-only history plus typed records on disk.
- **Front doors**: Claude/Cursor (MCP), Telegram, hermes-agent (each proven in CI).

Builder deep-dives: [Concepts](concepts/index.md) · [Architecture](architecture.md) ·
[Authoring guide](PACK_AUTHORING.md).

## License

MIT. See the repository `LICENSE`.
