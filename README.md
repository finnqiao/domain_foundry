# Domain Foundry

**Turn an interest into an evidence-backed app you own.**

**Domain Foundry** researches the real practice, compares three materially
different product concepts, derives a schema from the questions it must answer,
and compiles the chosen experience into a local application with its evidence,
data model, and build receipt.

> Evidence to concepts to schema to experience to owned app—one inspectable
> specification, not a staff-title prompt or generic dashboard.

<!--
  DEMO GIF PLACEHOLDER — do not commit a fabricated binary.
  The 90-second walkthrough (capture → routing badge → app timeline → correction)
  is a human recording gate; see LAUNCH_CHECKLIST.md. When recorded, drop it at
  docs/assets/demo.gif (captured from synthetic data only) and replace this line:
  ![Domain Foundry 90-second demo](docs/assets/demo.gif)
-->

_A 90-second demo GIF will live here once recorded (synthetic data only) — see [`LAUNCH_CHECKLIST.md`](LAUNCH_CHECKLIST.md)._

## What you get

1. **Research before generation** — reviewed sources and bounded live discovery
   ground domain vocabulary, workflows, and constraints.
2. **Compare real alternatives** — exactly three concepts must differ in loop,
   hierarchy, affordance, and workflow structure; remixing keeps lineage.
3. **Questions justify storage** — identities, events, relationships, time,
   constraints, and indexes trace back to named workloads and evidence.
4. **One spec, one product** — preview, SQLite DDL, owned app, provenance, and
   evaluation compile from the same strict `FoundrySpec`.
5. **Local ownership** — generated apps work offline, preserve correction
   versions, export and restore spec-bound JSON, and ship beside their evidence
   and content-hashed receipt. No telemetry.
6. **Independent proof** — user-authored tasks join fixed schema, accessibility,
   security, licensing, and reproducibility gates.

## Quickstart (5 minutes)

Packages are not on PyPI yet. From this checkout:

```bash
pip install -e .
# optional adapters: pip install -e ./adapters/mcp
domain-foundry setup               # bring your own key; pick where to start
domain-foundry serve
```

Open <http://127.0.0.1:8787>. Then say the first line of a weekend:

> i have a log of sourdough bakes

Open `/foundry` to inspect the three reviewed applications—Sourdough Lab, Card
Collector, and Japanese Study Coach—or enter a brief and two observable release
tasks to run the evidence-backed creation flow. The two interactive engineering
deliverables are the [end-to-end flow](docs/prototypes/foundry-flow.html) and
[knowledge fabric](docs/prototypes/knowledge-fabric.html).

`setup` asks which provider you have a key for, suggests models, and checks the
key. The reviewed goldens and local capture runtime need no model. Creating a
new Foundry proposal requires a configured reasoning model; an interest outside
the reviewed corpus also requires the optional Brave research adapter or a
reviewed source packet. It fails closed instead of claiming a keyword scaffold
was researched.

Already know the provider? Skip the questions:

```bash
domain-foundry setup --provider anthropic -y     # or openai / deepseek / openrouter / local / none
domain-foundry new-domain "i have a log of sourdough bakes"
```

Then pick a look and say **build it** (or **the scatter one** on the bake log).
`skip` is not install — it only shows a look. Terminal walkthrough:
[`docs/QUICKSTART.md`](docs/QUICKSTART.md).

Once the packages are on PyPI, an isolated pipx install of the core package will
work. Until then, the checkout is the install.

Install notes: **[Getting started](docs/tutorial/getting-started.md)**.

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
through the full loop (describe a passion → log → ask → fix) by an
automated end-to-end test in CI, and has a reproducible proof snapshot
(`python scripts/tutorial_snapshots.py`):

| Front door | Talk to it from | Setup (from this checkout) |
|---|---|---|
| **[MCP](adapters/mcp#readme)** | Claude Desktop, Cursor, any MCP client | `pip install -e ./adapters/mcp` + one config block |
| **[Telegram](adapters/telegram#readme)** | A bot you text from your phone | `pip install -e ./adapters/telegram` + @BotFather |
| **[hermes-agent](adapters/hermes_agent#readme)** | The hermes-agent runtime | plugin install into the Hermes env |

See **[Connect your chat app](docs/tutorial/connect-your-agent.md)** for copy-paste
configs and the proof snapshots.

## Documentation

A full MkDocs Material site lives under [`docs/`](docs/) (`mkdocs serve` to read
locally, or `pip install -e ".[docs]" && mkdocs build`):

- **[User stories & evidence](docs/USER_STORIES.md)** — what each audience gets,
  and the reproducible proof behind every claim (including what is *not* proven)
- **Foundry** — [redesign and gap-remediation record](docs/FOUNDRY_REDESIGN.md) ·
  [AI remix landscape](docs/remix-landscape.md) ·
  [replacement-name slate](docs/name-replacement-slate.md) ·
  [threat model](docs/concepts/foundry-threat-model.md) ·
  [knowledge contribution rules](knowledge/CONTRIBUTING.md)
- **Concepts** — [how notes are stored](docs/concepts/ledger.md) ·
  [how an interest is defined](docs/concepts/packs.md) ·
  [how filing works](docs/concepts/routing.md) ·
  [how a fix is kept](docs/concepts/corrections.md) ·
  [replay](docs/concepts/replay.md)
- **Authoring** — [guide](docs/PACK_AUTHORING.md) ·
  [remix in an afternoon](docs/tutorial-plant-care.md) ·
  [custom blocks](docs/CUSTOM_BLOCKS.md)
- **[Architecture](docs/architecture.md)** · **[Gallery](docs/gallery.md)** ·
  **[Adapter guide](docs/adapter-guide.md)** · **[Security](docs/security.md)**

## Architecture (sketch)

- **Python core** (`domain-foundry-core`) — storage, filing, corrections, views
- **FoundrySpec compiler** — research, concepts, schema, experience, exact app,
  evidence, and build receipt from one typed contract
- **Local server** — `domain-foundry serve` hosts the app and the shared API
- **React + Vite app shell** — remixable blocks driven by the interest you built
- **SQLite × 2** — append-only history + typed records on disk
- **Front doors** — Claude/Cursor (MCP), Telegram, hermes-agent (all CI-driven)
- **Bring your own key** — required for new evidence-backed proposals; never
  persisted in a Foundry brief

## Status

This checkout is a release candidate, not a published release. Automated
quality evidence is enforced by `scripts/release_audit.sh`; live provider
probes, an independent knowledge-corpus review, a manual screen-reader pass, an
independent dependency/source-license review, an external security review,
independent user validation, the demo recording, and package/name publication
remain human gates. See the
[redesign record](docs/FOUNDRY_REDESIGN.md) and
the [independent release-review protocol](docs/release-review-guide.md). The
public tag gate, `scripts/public_release_audit.py`, fails closed until those
reviews are bound to the exact clean source tree and artifacts. See also
[`docs/USER_STORIES.md`](docs/USER_STORIES.md) for deliberately unclaimed
evidence.

> **Name:** provisional public name is **Domain Foundry** (`domain-foundry-core` /
> CLI `domain-foundry`). A live US application for the exact mark covers directly
> overlapping software services, so publication under this name is blocked
> pending rename, a rights agreement, or qualified clearance — see
> [ADR-005](docs/adr/ADR-005-name-decision.md). The screened replacement slate
> recommends **Patternstead**, subject to maintainer choice and a fresh
> professional clearance search.

## Development

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check core tests scripts adapters
python scripts/clock_audit.py
python scripts/leakscan.py
scripts/release_audit.sh          # aggregate release-blocking gate
scripts/candidate_gate.sh         # rebuild + clean-install + hashed evidence
python scripts/review_packet.py prepare  # clean-candidate reviewer handoff
python scripts/review_packet.py seal     # bind final reports into receipts
python scripts/public_release_audit.py  # human receipts + publication authority
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and the
[gallery](docs/gallery.md#community-candidate-list) for good first interests.
Bug / submission / filing-miss issue templates are under
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/).

## License

MIT — see [LICENSE](LICENSE).
