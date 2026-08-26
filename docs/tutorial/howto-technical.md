# Domain Foundry for developers

Same weekend as the story page, from the terminal. Click-through of bake / dive /
cards: **[Bring the log. Pick a look.](end-to-end.html)**.

## The weekend, as commands

From a checkout:

```bash
git clone https://github.com/finnqiao/domain_foundry && cd domain_foundry
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# optional adapters: pip install -e ./adapters/mcp
domain-foundry init
```

Bake log:

```bash
domain-foundry new-domain "i have a log of sourdough bakes"
domain-foundry wizard reply <session> "i want to data visualize all my bakes"
domain-foundry wizard reply <session> "the scatter one"
domain-foundry ask "which hydrations actually sprang?"
domain-foundry correct "that sunday batard was 78 not 72"
```

Copy `<session>` from the first command’s JSON. “the scatter one” accepts the look
and builds it.

Card binder (look → critique → **build it** → a card files):

```bash
domain-foundry new-domain "i collect pokemon cards"
domain-foundry wizard reply <session> "a dex of the cards i own with photos"
domain-foundry wizard reply <session> "make the gallery denser"
domain-foundry wizard reply <session> "build it"
domain-foundry wizard reply <session> "pulled a holographic Charizard from a 151 booster, NM"
domain-foundry ask "which cards did I log?"
```

`skip` is not install. It only accepts the suggested idea and shows a look:

```bash
domain-foundry new-domain "I want to remember the animals I see underwater" --reply skip
domain-foundry wizard reply <session> "build it"
```

## What just happened

1. **`new-domain`** opened a neighborhood of apps you could build. Nothing is live.
2. Your reply picked a job (visualize / photos / field guide). Foundry sketched a look.
3. **the scatter one** or **build it** compiled that look onto your computer.
4. **ask** reads your records. A one-sentence **correct** amends the row; history stays.

The ledger, L1/L2 filing, and YAML definitions live in
[Concepts](../concepts/index.md). Sketch below if you want it on this page.

Data lives at `~/.domain_foundry` (override with `--home` or `DOMAIN_FOUNDRY_HOME`)
— two SQLite files: `ledger.sqlite` (captures, corrections, cost) and
`domains.sqlite` (typed rows). Open them with any SQLite browser; there's no magic.

Install the other tested adapters when you need them:

```bash
pip install -e ./adapters/mcp -e ./adapters/telegram -e ./adapters/hermes_agent
```

---

## Mental model

```
capture (raw text) ──► ledger (append-only, SQLite)
                          │
                          ▼
                    route  ── L1 rules (zero-cost) ─► confident? file it
                          └─ L2 LLM (on ambiguity) ─► review / Inbox if not
                          │
                          ▼
                    canonical objects (typed rows) ──► views (vault, app, maps)
                          ▲
                    correct (one message) ──► amends the row + writes a replay case
```

Four invariants worth internalizing:

1. **Capture is first and durable.** Raw text + where it came from are written before any
   interpretation. Nothing is dropped; uncertainty becomes a review or Inbox card.
2. **Domains are data, not code.** A pack is a folder of YAML (schema, routing
   rules, policy, projections). The wizard generates one from a plain-language goal.
3. **Writes share one contract.** `HarnessAPI` writes straight to SQLite, and
   the FastAPI daemon serves the same read/write contract for the SPA and
   remote adapters. Every write surface (CLI, MCP, Telegram, hermes-agent)
   can use the canonical HTTP seam or an in-process embedding that passes
   conformance.
4. **Corrections compound.** Each fix amends the canonical record *and* compiles
   into a replayable eval case, so the system provably improves.

---

## Routing & LLM backends

L1 is deterministic keyword rules (no cost). L2 escalates to an LLM only on
ambiguity. Bring your own key — any OpenAI-compatible endpoint works, plus the
Anthropic Messages API.

Settings resolve **env > config file > provider default**, so pick whichever
layer suits you. Env only, as before:

```bash
# DeepSeek (native API — cheapest per capture; design uses deepseek-v4-pro)
export DEEPSEEK_API_KEY=...
export DOMAIN_FOUNDRY_LLM=live
domain-foundry setup --provider deepseek -y

# OpenRouter (one key, many models)
export OPENROUTER_API_KEY=...
export DOMAIN_FOUNDRY_LLM=live
export DOMAIN_FOUNDRY_ROUTINE_BASE_URL=https://openrouter.ai/api/v1
export DOMAIN_FOUNDRY_ROUTINE_API_KEY=$OPENROUTER_API_KEY
export DOMAIN_FOUNDRY_ROUTINE_MODEL=z-ai/glm-5.2
export DOMAIN_FOUNDRY_SOTA_BASE_URL=https://openrouter.ai/api/v1
export DOMAIN_FOUNDRY_SOTA_API_KEY=$OPENROUTER_API_KEY
export DOMAIN_FOUNDRY_SOTA_MODEL=google/gemini-2.5-pro
```

Or persist it once and stop exporting things:

```bash
domain-foundry setup --provider deepseek -y     # or openrouter / anthropic
domain-foundry setup --show                     # resolved values + their source
```

`setup --provider deepseek` writes routine=`deepseek-v4-flash` and
sota=`deepseek-v4-pro` against `https://api.deepseek.com`. Mix tiers if you
want a stronger designer than your everyday router — env vars win over the file.

With no key it runs the heuristic router (deterministic, keyword-only) — great for
tests, limited for free-text. A daily cost guard caps spend
(`DOMAIN_FOUNDRY_DAILY_COST_CAP`, default `$0.25`).

One key is enough. Routing has two tiers — `routine` for ordinary captures and
`sota` for ambiguous ones (a capture that matches no keyword rule, which is every
capture into a brand-new domain) — and a tier with no key of its own falls back to
whichever tier is configured. Set `DOMAIN_FOUNDRY_SOTA_*` separately only when you
want a stronger model on the hard calls; any OpenAI-compatible base URL works
there too, not just Anthropic's.

### Per-model request shape (Anthropic)

Anthropic's request shape varies by model, and getting it wrong is a 400 that the
router swallows into keyword routing — so it is resolved from a capability table
(`llm/providers.py`) rather than guessed:

| | `temperature` | `output_config.effort` |
|---|---|---|
| Opus 5 / 4.8 / 4.7, Sonnet 5, Fable 5 | rejected (400) | accepted |
| Opus 4.6, Sonnet 4.6 | accepted | accepted |
| Haiku 4.5 | accepted | rejected |

Unrecognised models get the conservative shape (no sampling params, no optional
extras) on the theory that an unknown model is likelier newer than older, and a
400 on the sota tier is invisible. If an optional parameter *is* rejected, the
call retries once with a minimal body; a 401/429/5xx does not retry, because
dropping parameters cannot fix it. `DOMAIN_FOUNDRY_SOTA_EFFORT` overrides effort
(default `medium`).

Native structured outputs (`output_config.format`) are deliberately **not** used
for routing: `ROUTE_SCHEMA` carries a free-form `fields` object whose keys are
defined by whichever pack matched, and strict structured outputs require
`additionalProperties: false`. Prompt-and-parse plus key-synonym tolerance is what
keeps dynamic pack schemas working across every BYO backend.

## Bolt existing data on (ingest)

```bash
domain-foundry ingest ~/Notes/baking --dry-run          # preview routing (no writes)
domain-foundry ingest ~/Notes/baking                    # pull in (idempotent)
domain-foundry ingest ~/Notes --only sourdough          # only notes that route here
domain-foundry ingest ~/logs/journal.log --split lines    # one capture per line
domain-foundry ingest ~/Notes/baking --watch            # re-scan, pull in new notes

# in the app: `domain-foundry serve` → Settings → Sources (same engine)
```

Read-only at the source, idempotent on `(channel, source_ref)`. For a **structured**
source (a SQLite table, a JSON/JSONL export) use the mapping-driven importer:

```bash
domain-foundry import -m map.yaml --sqlite ~/old.db                  # dry-run
domain-foundry import -m map.yaml --sqlite ~/old.db --table e=tbl \
    --where e="deleted_at IS NULL" --markdown                        # remap + filter
domain-foundry import -m map.yaml --json ~/export/ --apply            # write
```

Databases are opened `mode=ro`. Every row is classified imported / skipped /
failed and the command exits non-zero unless all of them are accounted for, so a
partial migration fails loudly. Mapping examples: `examples/importers/*.yaml`.
Same engine from Python if you prefer:
`domain_foundry_core.migrations.importers` (`GenericImporter`,
`SqliteTableSource`, `FixtureSource`, `load_mapping`).

## Connect an agent (the three tested harnesses)

| Harness | Command / entry | CI proof |
|---|---|---|
| **MCP** | `domain-foundry-mcp` (stdio server) | `adapters/mcp/tests/test_mcp_e2e.py` |
| **Telegram** | `domain-foundry-telegram` (long-poll bot) | `adapters/telegram/tests/test_telegram_bridge.py` |
| **hermes-agent** | plugin, `register(ctx)` entry point | `adapters/hermes_agent/tests/test_hermes_e2e.py` |

Copy-paste configs and proof transcripts: [Connect your agent](connect-your-agent.md).
Any MCP-capable runtime works through the MCP server; that's the recommended path
for a new integration.

## HTTP API

```bash
domain-foundry serve                 # http://127.0.0.1:8787  (Settings → Sources)
```

Reads are plain GETs: `/api/query`, `/api/review`, `/api/packs`,
`/api/blocks/<domain>/…`, `/api/objects/…`; the daemon also serves JSON writes
such as `/api/capture`, `/api/correct`, and `/api/wizard`. The filesystem-scoped
ingest operation remains local server-side: `POST /api/ingest/preview`
(read-only) and `POST /api/ingest` (commit) let the *local* server pull in
*local* files, which powers **Settings → Sources**. Set `DOMAIN_FOUNDRY_API_TOKEN`
to require a bearer token on every endpoint.

## Author a domain pack

A pack is data. See the [pack authoring guide](../PACK_AUTHORING.md) for the full
schema; remix a real one in an afternoon with the
[plant-care tutorial](../tutorial-plant-care.md). The wizard's output under
`~/.domain_foundry/packs/<name>/` is a fine starting point to hand-edit.

## Run the tests

```bash
python -m pytest tests adapters/mcp/tests adapters/telegram/tests adapters/hermes_agent/tests
# → full suite green, 2 skipped   (the skips are live-LLM smokes; see the runbook §9)
```

Full verification — every surface, with expected output and troubleshooting — is
in the **[end-to-end testing runbook](testing-runbook.md)**. Regenerate the proof
snapshots any time with `python scripts/tutorial_snapshots.py`.

## Extend it — where the seams are

| Want to… | Look at |
|---|---|
| Add an LLM provider | `core/domain_foundry_core/llm/provider.py` |
| Change routing / tiers | `core/domain_foundry_core/routing/router.py` |
| Add an ingest source type | `core/domain_foundry_core/ingest.py` (unstructured) or `migrations/importers/source.py` (structured) |
| Add an agent runtime | mirror an adapter in `adapters/` — wrap `HarnessAPI`, ship a CI e2e test |
| Add an app block/view | `app/src/blocks/` (+ `/api/blocks/<domain>/…`) |
| New projection target | `core/domain_foundry_core/projections/` |

Contributions follow the [contributing guide](https://github.com/finnqiao/domain_foundry/blob/main/CONTRIBUTING.md);
the release gate runs leak-scan, a frozen-clock audit, eval replay, ruff, and the
full suite.
