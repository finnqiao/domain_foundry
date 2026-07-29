# Domain Foundry

**Describe your passion. Get an app. Talk to it.**

**Domain Foundry** (`domain-foundry`) is a local-first personal agent harness that
turns natural-language captures into structured, domain-specific data and usable
applications — remixable to any domain that is your passion.

> The structured-life data layer for agent runtimes.

<!--
  DEMO GIF PLACEHOLDER — do not commit a fabricated binary.
  The 90-second walkthrough (capture → routing badge → app timeline → correction)
  is a human recording gate; see LAUNCH_CHECKLIST.md. When recorded, drop it at
  docs/assets/demo.gif (captured from synthetic packs only) and replace this line:
  ![Domain Foundry 90-second demo](docs/assets/demo.gif)
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
pipx install domain-foundry-core   # or, from a checkout: pip install -e .
domain-foundry setup               # bring your own key; pick where to start
domain-foundry serve
```

`setup` is the guided path: it asks which provider you have a key for, suggests a
model for each tier, makes one cheap live call to prove the key actually works,
then asks what you want to do first — start from a ready-made log, describe your
own, pull in notes you already have, or attach a database.

Already know what you want? Skip every question:

```bash
domain-foundry setup --provider anthropic -y     # or openai / deepseek / openrouter / local / none
domain-foundry init && domain-foundry pack add food
```

Environment variables (`DOMAIN_FOUNDRY_SOTA_MODEL`, `…_API_KEY`, `…_BASE_URL`)
override anything `setup` writes, so a config that lives in your dotfiles keeps
working and needs no config file at all. `domain-foundry setup --show` prints
what every setting resolved to, and where it came from, with keys redacted.

Then open <http://127.0.0.1:8787> and capture from the web box or CLI:

```bash
domain-foundry capture "cooked a batch of shoyu ramen, came out great"
domain-foundry query --domain food
domain-foundry health
```

New here? Start with **[Getting started](docs/tutorial/getting-started.md)** — a
two-track tutorial (talk to it in an app, or use the CLI). Full CLI walkthrough in
[`docs/QUICKSTART.md`](docs/QUICKSTART.md); automated clean-machine gate via
`scripts/quickstart_gate.sh`.

## Already have data? Bolt it on

Domain Foundry is a layer, not a rewrite. Both on-ramps are read-only,
idempotent, and dry-run by default — see
**[Bolt it onto your existing setup](docs/tutorial/adopt-in-place.md)**.

```bash
# free-text notes: a folder, a journal, an Obsidian vault
domain-foundry ingest ~/Notes --dry-run        # preview where each note lands
domain-foundry ingest ~/Notes --watch          # keep pulling in new ones

# structured sources: a SQLite table, a JSON/JSONL export
domain-foundry import -m my_mapping.yaml --sqlite ~/old-app.sqlite   # dry-run
domain-foundry import -m my_mapping.yaml --sqlite ~/old-app.sqlite --apply
```

Your sources are never written to — databases are opened `mode=ro`, notes are
never moved or edited — and `import` exits non-zero unless every source row is
accounted for, so a partial migration can't pass quietly.

## Connect your agent — three tested harnesses

Talk to Domain Foundry from wherever you already are. Each of these is driven
through the full loop (create a domain → capture → query → correct) by an
automated end-to-end test in CI, and has a reproducible proof snapshot
(`python scripts/tutorial_snapshots.py`):

| Harness | Talk to it from | Setup |
|---|---|---|
| **[MCP](adapters/mcp#readme)** | Claude Desktop, Cursor, any MCP client | `pipx install domain-foundry-mcp` + one config block |
| **[Telegram](adapters/telegram#readme)** | A bot you text from your phone | `pipx install domain-foundry-telegram` + @BotFather |
| **[hermes-agent](adapters/hermes_agent#readme)** | The hermes-agent runtime | plugin install into the Hermes env |

See **[Connect your agent](docs/tutorial/connect-your-agent.md)** for copy-paste
configs and the proof snapshots. Any other MCP-capable runtime works through the
MCP server; non-MCP runtimes use the read-only HTTP API plus the in-process write
path — community-supported, not CI-gated.

## Documentation

A full MkDocs Material site lives under [`docs/`](docs/) (`mkdocs serve` to read
locally, or `pip install -e ".[docs]" && mkdocs build`):

- **[User stories & evidence](docs/USER_STORIES.md)** — what each audience gets,
  and the reproducible proof behind every claim (including what is *not* proven)
- **Concepts** — [ledger](docs/concepts/ledger.md) · [packs](docs/concepts/packs.md) ·
  [routing](docs/concepts/routing.md) · [corrections](docs/concepts/corrections.md) ·
  [evaluation replay](docs/concepts/replay.md)
- **Authoring** — [pack authoring guide](docs/PACK_AUTHORING.md) ·
  [remix in an afternoon](docs/tutorial-plant-care.md) ·
  [custom blocks](docs/CUSTOM_BLOCKS.md)
- **[Architecture](docs/architecture.md)** · **[Pack gallery](docs/gallery.md)** ·
  **[Adapter guide](docs/adapter-guide.md)** · **[Security](docs/security.md)**

## Architecture (sketch)

- **Python core** (`domain-foundry-core`) — ledger, packs, routing, apply, projections
- **FastAPI** — `HarnessAPI` + SPA static assets (`domain-foundry serve`)
- **React + Vite app shell** — remixable blocks driven by pack projections
- **SQLite × 2** — `ledger.sqlite` (substrate) + `domains.sqlite` (pack tables)
- **Adapters** — hermes-agent plugin, MCP server, Telegram bridge (all CI-driven)
- **Bring your own key** — provider registry + `~/.domain_foundry/config.toml`,
  resolving env > config > default; two model tiers with automatic escalation

## Status

The core is complete through the plan's P0–P8 phases: capture substrate, hybrid
routing, apply + corrections, projections + review API, the universal app shell,
the domain-creation wizard, the evaluation-replay framework, and reference packs
+ the hermes-agent adapter. P9 (docs, audit, launch prep) is in this release,
along with bring-your-own-key onboarding (`setup`) and the structured-source
importer (`import`). See [`docs/PHASE_STATUS.md`](docs/PHASE_STATUS.md),
[`docs/USER_STORIES.md`](docs/USER_STORIES.md) and
[`CHANGELOG.md`](CHANGELOG.md).

**Gates:** 281 passed / 2 skipped · ruff clean · `release_audit.sh` 8/8 ·
`quickstart_gate.sh` green. Remaining work is human gates — PyPI name
availability, the demo GIF, an external security pass, a lived production week,
and one live `setup --probe` per documented provider. Per-claim evidence, and
what is deliberately *not* proven, is in
[`docs/USER_STORIES.md`](docs/USER_STORIES.md).

> **Name:** provisional public name is **Domain Foundry** (`domain-foundry-core` /
> CLI `domain-foundry`). Availability + trademark checks before publish remain a
> human gate — see [ADR-005](docs/adr/ADR-005-name-decision.md).

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
