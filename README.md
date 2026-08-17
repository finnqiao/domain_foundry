# Domain Foundry

**Describe your passion. Get an app. Talk to it.**

**Domain Foundry** turns what you say into neat, correctable notes for the things
you care about — baking, plants, travel, or anything you describe — and keeps
them on your own computer.

> Say what happened. See it filed. Fix a mistake in one sentence. It stays local.

<!--
  DEMO GIF PLACEHOLDER — do not commit a fabricated binary.
  The 90-second walkthrough (capture → routing badge → app timeline → correction)
  is a human recording gate; see LAUNCH_CHECKLIST.md. When recorded, drop it at
  docs/assets/demo.gif (captured from synthetic packs only) and replace this line:
  ![Domain Foundry 90-second demo](docs/assets/demo.gif)
-->

_A 90-second demo GIF will live here once recorded (synthetic data only) — see [`LAUNCH_CHECKLIST.md`](LAUNCH_CHECKLIST.md)._

## What you get

1. **Write it down first** — your exact words are saved before anything is sorted.
2. **Never lose a note** — if it isn't sure where something belongs, it waits in Inbox.
3. **Fix it in one sentence** — say “actually it was Tuesday” and the record updates.
4. **Your passion, your app** — describe an interest; get a place to log and browse it.
5. **Local first** — data lives in plain files on your machine; no telemetry.
6. **Gets better when you correct it** — each fix teaches it for next time.

## Quickstart (5 minutes)

```bash
# From this checkout (PyPI publish is still a human launch gate):
pip install -e .
# After publish: pipx install domain-foundry-core
domain-foundry setup               # bring your own key; pick where to start
domain-foundry serve
```

`setup` asks which provider you have a key for, suggests models, checks the key
works, then asks what you want to do first — start from a ready-made log, describe
your own, or pull in notes you already have.

Already know what you want? Skip every question:

```bash
domain-foundry setup --provider anthropic -y     # or openai / deepseek / openrouter / local / none
domain-foundry init && domain-foundry pack add food
```

Environment variables (`DOMAIN_FOUNDRY_SOTA_MODEL`, `…_API_KEY`, `…_BASE_URL`)
override anything `setup` writes. `domain-foundry setup --show` prints what
resolved, with keys redacted.

Then open <http://127.0.0.1:8787> and log from the app or CLI:

```bash
domain-foundry capture "cooked a batch of shoyu ramen, came out great"
domain-foundry query --domain food
domain-foundry health
```

New here? Start with **[Getting started](docs/tutorial/getting-started.md)** —
no terminal after install, or the CLI track. Story version:
**[Turn a hobby into an app](docs/tutorial/end-to-end.html)**. Full CLI walkthrough in
[`docs/QUICKSTART.md`](docs/QUICKSTART.md).

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

## Connect your chat app

Talk to Domain Foundry from wherever you already are. Each of these is driven
through the full loop (describe a passion → log → ask → correct) by an
automated end-to-end test in CI, and has a reproducible proof snapshot
(`python scripts/tutorial_snapshots.py`):

| Front door | Talk to it from | Setup |
|---|---|---|
| **[MCP](adapters/mcp#readme)** | Claude Desktop, Cursor, any MCP client | `pipx install domain-foundry-mcp` + one config block |
| **[Telegram](adapters/telegram#readme)** | A bot you text from your phone | `pipx install domain-foundry-telegram` + @BotFather |
| **[hermes-agent](adapters/hermes_agent#readme)** | The hermes-agent runtime | plugin install into the Hermes env |

See **[Connect your chat app](docs/tutorial/connect-your-agent.md)** for copy-paste
configs and the proof snapshots.
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

- **Python core** (`domain-foundry-core`) — storage, routing, corrections, views
- **Local server** — `domain-foundry serve` hosts the app and the shared API
- **React + Vite app shell** — remixable blocks driven by passion definitions
- **SQLite × 2** — append-only history + typed records on disk
- **Front doors** — Claude/Cursor (MCP), Telegram, hermes-agent (all CI-driven)
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

**Gates:** full pytest suite green (2 opt-in live-LLM skips) · ruff clean · pyright 0 errors ·
`release_audit.sh` green · `quickstart_gate.sh` green · GitHub Actions `ci` and
`leakscan` green on Python 3.11/3.12/3.13. Remaining work is human gates — the
demo GIF, an external security pass, a lived production week, one live
`setup --probe` per documented provider, and claiming the (verified available)
PyPI names. Per-claim evidence, and what is deliberately *not* proven, is in
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
