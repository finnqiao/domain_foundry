# domain_expert

**Describe your passion. Get an app. Talk to it.**

`domain_expert` is a local-first personal agent harness that turns natural-language
captures into structured, domain-specific data and usable applications — remixable
to any domain that is your passion.

> The structured-life data layer for agent runtimes.

<!--
  DEMO GIF PLACEHOLDER — do not commit a fabricated binary.
  The 90-second walkthrough (capture → routing badge → app timeline → correction)
  is a human recording gate; see LAUNCH_CHECKLIST.md. When recorded, drop it at
  docs/assets/demo.gif (captured from synthetic packs only) and replace this line:
  ![domain_expert 90-second demo](docs/assets/demo.gif)
-->

_A 90-second demo GIF will live here once recorded (synthetic data only) — see [`LAUNCH_CHECKLIST.md`](LAUNCH_CHECKLIST.md)._

## Product promise

1. **Capture first** — raw message + provenance are stored before interpretation.
2. **Never drop** — ambiguity becomes review, an unfiled card, or ledger-only state.
3. **One-message corrections** — fix the canonical record; history is preserved.
4. **Your app, your schema** — describe a domain; get a working pack and app view.
5. **Local first** — canonical data lives in SQLite on your machine; no telemetry.
6. **Provably improving** — corrections become replayable eval cases.

## Quickstart (5 minutes)

```bash
pipx install domain-expert-core   # or, from a checkout: pip install -e .
domain-expert init
domain-expert pack add packs/food     # or plants / sourdough / travel
domain-expert serve
```

Then open <http://127.0.0.1:8787> and capture from the web box or CLI:

```bash
domain-expert capture "cooked a batch of shoyu ramen, came out great"
domain-expert query --domain food
domain-expert health
```

Full walkthrough (packs + optional hermes-agent hookup) in
[`docs/QUICKSTART.md`](docs/QUICKSTART.md); run the automated clean-machine gate
with `scripts/quickstart_gate.sh`.

## Documentation

A full MkDocs Material site lives under [`docs/`](docs/) (`mkdocs serve` to read
locally, or `pip install -e ".[docs]" && mkdocs build`):

- **Concepts** — [ledger](docs/concepts/ledger.md) · [packs](docs/concepts/packs.md) ·
  [routing](docs/concepts/routing.md) · [corrections](docs/concepts/corrections.md) ·
  [evaluation replay](docs/concepts/replay.md)
- **Authoring** — [pack authoring guide](docs/PACK_AUTHORING.md) ·
  [remix in an afternoon](docs/tutorial-plant-care.md) ·
  [custom blocks](docs/CUSTOM_BLOCKS.md)
- **[Architecture](docs/architecture.md)** · **[Pack gallery](docs/gallery.md)** ·
  **[Adapter guide](docs/adapter-guide.md)** · **[Security](docs/security.md)**

## Architecture (sketch)

- **Python core** (`domain-expert-core`) — ledger, packs, routing, apply, projections
- **FastAPI** — `HarnessAPI` + SPA static assets (`domain-expert serve`)
- **React + Vite app shell** — remixable blocks driven by pack projections
- **SQLite × 2** — `ledger.sqlite` (substrate) + `domains.sqlite` (pack tables)
- **Adapters** — hermes-agent plugin first; MCP later

## Status

The core is complete through the plan's P0–P8 phases: capture substrate, hybrid
routing, apply + corrections, projections + review API, the universal app shell,
the domain-creation wizard, the evaluation-replay framework, and reference packs
+ the hermes-agent adapter. P9 (docs, audit, launch prep) is in this release.
See [`docs/PHASE_STATUS.md`](docs/PHASE_STATUS.md) and
[`CHANGELOG.md`](CHANGELOG.md).

> **Name:** the working name is `domain_expert` / `domain-expert`. The final
> public product name is an open decision (front-runner **Trellis**) — see
> [ADR-005](docs/adr/ADR-005-name-decision.md). Nothing in the code depends on
> it, so a rename is mechanical.

## Development

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check core tests scripts adapters
python scripts/clock_audit.py
python scripts/leakscan.py
scripts/release_audit.sh          # aggregate release-blocking gate
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and the
[pack gallery](docs/gallery.md#community-candidate-list) for good first packs.
Bug / pack-submission / routing-miss issue templates are under
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/).

## License

MIT — see [LICENSE](LICENSE).
