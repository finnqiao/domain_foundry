# domain_expert

**Describe your passion. Get an app. Talk to it.**

`domain_expert` is a local-first personal agent harness that turns natural-language
captures into structured, domain-specific data and usable applications — remixable
to any domain that is your passion.

> The structured-life data layer for agent runtimes.

## Product promise

1. **Capture first** — raw message + provenance are stored before interpretation.
2. **Never drop** — ambiguity becomes review, an unfiled card, or ledger-only state.
3. **One-message corrections** — fix the canonical record; history is preserved.
4. **Your app, your schema** — describe a domain; get a working pack and app view.
5. **Local first** — canonical data lives in SQLite on your machine.
6. **Provably improving** — corrections become replayable eval cases.

## Quickstart (5 minutes)

```bash
pipx install domain-expert-core   # or: pip install -e .
domain-expert init
domain-expert pack add packs/food     # or plants / sourdough / travel
domain-expert serve
```

Then open http://127.0.0.1:8787 and capture from the web box or CLI:

```bash
domain-expert capture "cooked a batch of shoyu ramen, came out great"
domain-expert query --domain food
domain-expert health
```

Full walkthrough (packs + optional hermes-agent hookup) in
[`docs/QUICKSTART.md`](docs/QUICKSTART.md); run the automated clean-machine gate
with `scripts/quickstart_gate.sh`.

## Status

This repository is in early public construction (P0/P1 substrate).
Domain packs, hybrid routing, corrections→evals, and the universal app shell
land in subsequent phases — see `docs/OPEN_SOURCE_HARNESS_PLAN.md`.

## Architecture (sketch)

- **Python core** (`domain-expert-core`) — ledger, packs, routing, apply, projections
- **FastAPI** — `HarnessAPI` + SPA static assets (`domain-expert serve`)
- **React + Vite app shell** — remixable blocks driven by pack projections
- **SQLite × 2** — `ledger.sqlite` (substrate) + `domains.sqlite` (pack tables)
- **Adapters** — hermes-agent plugin first; MCP later

## Development

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check core tests
```

## License

MIT — see [LICENSE](LICENSE).
