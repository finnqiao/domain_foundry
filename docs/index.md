# Domain Foundry

**Describe your passion. Get an app. Talk to it.**

**Domain Foundry** is a local-first personal agent harness that turns
natural-language captures into structured, domain-specific data and a usable
application — remixable to any domain you care about.

> The structured-life data layer for agent runtimes.

!!! note "Name"
    Provisional public name: **Domain Foundry** (`domain-foundry-core` /
    CLI `domain-foundry`). PyPI / GitHub / trademark availability before publish
    is still a human gate — see [ADR-005](adr/ADR-005-name-decision.md).

## The six promises

1. **Capture first** — the raw message + provenance are stored *before* interpretation.
2. **Never drop** — ambiguity becomes a review card, an unfiled entry, or ledger-only
   state; nothing is silently discarded.
3. **One-message corrections** — fix the canonical record in plain language; history is preserved.
4. **Your app, your schema** — describe a domain, get a working pack and app view.
5. **Local first** — canonical data lives in SQLite on your machine; no telemetry.
6. **Provably improving** — every correction becomes a replayable evaluation case.

## Where to start

<div class="grid cards" markdown>

- :material-rocket-launch: **[Quickstart](QUICKSTART.md)**

    Clean machine to a captured-into domain in minutes.

- :material-lightbulb-on: **[Concepts](concepts/index.md)**

    The ledger, packs, routing, corrections, and replay.

- :material-package-variant: **[Pack authoring](PACK_AUTHORING.md)**

    The quality bar for a good Domain Pack.

- :material-flask: **[Remix in an afternoon](tutorial-plant-care.md)**

    Build a plant-care pack from scratch.

- :material-sitemap: **[Architecture](architecture.md)**

    End-to-end data flow, module by module.

- :material-shield-lock: **[Security](security.md)**

    Local binding, token auth, path safety, SQL parameterization.

</div>

## Architecture at a glance

- **Python core** (`domain-foundry-core`) — ledger, packs, routing, apply, projections.
- **FastAPI** — the `HarnessAPI` surface + SPA static assets (`domain-foundry serve`).
- **React + Vite app shell** — remixable blocks driven by pack projections.
- **SQLite × 2** — `ledger.sqlite` (substrate) + `domains.sqlite` (pack tables).
- **Adapters** — a hermes-agent plugin first; MCP later.

## License

MIT. See the repository `LICENSE`.
