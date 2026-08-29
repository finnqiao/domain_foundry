# Domain Foundry

**Tell it what you are into. Get an app you own.**

Domain Foundry reads up on how people actually do the thing, offers you three
different ways to build it, works out what the app needs to store, then builds
the one you pick. It runs on your machine, and you can open every step it took.

> One plan you can read, and the app comes from it. Not a chat box in front of a
> template.

<!--
  DEMO GIF PLACEHOLDER. Do not commit a fabricated binary.
  The 90-second walkthrough (capture → routing badge → app timeline → correction)
  is a human recording gate; see LAUNCH_CHECKLIST.md. When recorded, drop it at
  docs/assets/demo.gif (captured from synthetic data only) and replace this line:
  ![Domain Foundry 90-second demo](docs/assets/demo.gif)
-->

_A 90-second demo will live here once it is recorded, from made-up data only. See [`LAUNCH_CHECKLIST.md`](LAUNCH_CHECKLIST.md)._

## What you get

1. **It reads up on your interest first.** Reviewed sources and a bounded live
   search set the vocabulary, the workflows, and the limits before anything is
   generated.
   <!-- proof: tests/unit/test_foundry_research_retrieval.py -->
2. **Three real choices, not three colour schemes.** A run produces three
   concepts that differ in loop, hierarchy, and workflow, and a remix records
   where each borrowed piece came from.
   <!-- proof: tests/unit/test_foundry_pipeline.py -->
3. **Every table earns its place.** Identities, events, relationships, dates,
   rules, and indexes each trace back to a named job and a named source.
   <!-- proof: tests/unit/test_foundry_spec.py -->
4. **One spec builds the whole thing.** The preview, the SQLite schema, the app
   you own, the provenance, and the evaluation all come from the same checked
   `FoundrySpec`.
   <!-- proof: scripts/foundry_audit.py -->
5. **The app is yours and works offline.** It keeps every version of a
   correction, exports and restores its own JSON, and ships next to its
   evidence and a hashed build receipt. Nothing is sent anywhere.
   <!-- proof: tests/contract/test_export.py -->
6. **Proof you did not write yourself.** Your own release tasks run next to
   fixed schema, accessibility, security, licensing, and reproducibility gates.
   <!-- proof: scripts/release_audit.sh -->

## Not true yet

Being honest about what is still being built. Each line names the work that will
make it true. `python scripts/claims_audit.py` checks that this list and the one
above stay accurate.

- **Two apps for two different interests look and work differently, not just in
  colour.** Today the generated apps share one layout. The spec already
  describes typography, density, and signature parts; the compiler is learning
  to render them.
  <!-- pending: Lane B, the experience compiler, proved by Lane G's difference gate -->
- **Your app is born with your history already in it.** One command that reads a
  spreadsheet, a notes folder, or an export from another app, and fills the new
  app with it.
  <!-- pending: Lane E, the seed pipeline -->
- **Mark up a look and have the build follow your marks.** Editable tokens, a
  look that binds, and a page you can annotate.
  <!-- pending: Lane C, the taste and review loop -->
- **One interest can build on another.** Packs that extend and import other
  packs, with real links between them.
  <!-- pending: Lane D, pack composition -->
- **An interest nobody wrote a pack for still gets an honest app.** Model
  knowledge is marked as model knowledge, and the generic fallback stops
  pretending.
  <!-- pending: Lane F, breadth and the trait graph -->
- **Start from someone else's app and keep the trail.** A fork that records what
  it came from.
  <!-- pending: Lane G, the minimal fork -->

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

Open `/foundry` to look through the three reviewed applications: Sourdough Lab,
Card Collector, and Japanese Study Coach. Or write a short brief and two things
you want to be able to do, and run the whole creation flow yourself. The two
interactive engineering deliverables are the
[end-to-end flow](docs/prototypes/foundry-flow.html) and the
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
`skip` does not install anything. It only shows you a look. Terminal walkthrough:
[`docs/QUICKSTART.md`](docs/QUICKSTART.md).

Once the packages are on PyPI, an isolated pipx install of the core package will
work. Until then, the checkout is the install.

Install notes: **[Getting started](docs/tutorial/getting-started.md)**.

## Already have data? Bolt it on

Domain Foundry is a layer, not a rewrite. Both on-ramps are read-only,
idempotent, and a dry run by default. See
**[Bolt it onto your existing setup](docs/tutorial/adopt-in-place.md)**.

```bash
# free-text notes: a folder, a journal, an Obsidian vault
domain-foundry ingest ~/Notes --dry-run        # preview where each note lands
domain-foundry ingest ~/Notes --watch          # keep pulling in new ones

# structured sources: a SQLite table, a JSON/JSONL export
domain-foundry import -m my_mapping.yaml --sqlite ~/old-app.sqlite   # dry-run
domain-foundry import -m my_mapping.yaml --sqlite ~/old-app.sqlite --apply
```

Your sources are never written to. Databases are opened read only, and notes
are never moved or edited. `import` also stops with an error unless every source
row is accounted for, so a half-finished import cannot pass quietly.

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

- **[User stories & evidence](docs/USER_STORIES.md)**: what each audience gets,
  and the reproducible proof behind every claim (including what is *not* proven)
- **Foundry**: [redesign and gap-remediation record](docs/FOUNDRY_REDESIGN.md) ·
  [AI remix landscape](docs/remix-landscape.md) ·
  [replacement-name slate](docs/name-replacement-slate.md) ·
  [threat model](docs/concepts/foundry-threat-model.md) ·
  [knowledge contribution rules](knowledge/CONTRIBUTING.md)
- **Concepts**: [how notes are stored](docs/concepts/ledger.md) ·
  [how an interest is defined](docs/concepts/packs.md) ·
  [how filing works](docs/concepts/routing.md) ·
  [how a fix is kept](docs/concepts/corrections.md) ·
  [replay](docs/concepts/replay.md)
- **Authoring**: [guide](docs/PACK_AUTHORING.md) ·
  [remix in an afternoon](docs/tutorial-plant-care.md) ·
  [custom blocks](docs/CUSTOM_BLOCKS.md)
- **[Architecture](docs/architecture.md)** · **[Gallery](docs/gallery.md)** ·
  **[Adapter guide](docs/adapter-guide.md)** · **[Security](docs/security.md)**

## Architecture (sketch)

- **Python core** (`domain-foundry-core`): storage, filing, corrections, views
- **FoundrySpec compiler**: research, concepts, schema, experience, exact app,
  evidence, and build receipt from one typed contract
- **Local server**: `domain-foundry serve` hosts the app and the shared API
- **React + Vite app shell**: remixable blocks driven by the interest you built
- **SQLite × 2**: append-only history plus typed records on disk
- **Front doors**: Claude/Cursor (MCP), Telegram, hermes-agent (all CI-driven)
- **Bring your own key**: required for new evidence-backed proposals, and never
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
> pending rename, a rights agreement, or qualified clearance. See
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

MIT. See [LICENSE](LICENSE).
