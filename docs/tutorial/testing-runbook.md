# End-to-end testing runbook

**Who this is for:** anyone verifying that Domain Foundry works: a contributor
before a PR, a maintainer before a release, or you, kicking the tires after
install. **Time:** 2 minutes for the automated pass, ~15 for the full manual sweep.

Every command below is copy-paste and shows the output you should see. If a step's
output matches, that surface works.

!!! note "One rule"
    Nothing here touches real data. Every command uses a throwaway `--home` or a
    temp workspace, and the router runs in **heuristic** mode (no API key, fully
    deterministic) unless you opt into a live model.

The same weekend as the public story: bake log → look → **build it** → ask → fix.
Click-through: **[Bring the log. Pick a look.](end-to-end.html)**.

---

## 0. Prerequisites

```bash
git clone https://github.com/finnqiao/domain_foundry && cd domain_foundry
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ./adapters/mcp -e ./adapters/telegram -e ./adapters/hermes_agent
```

Verify the CLI is on your PATH:

```console
$ domain-foundry version
0.1.0
```

---

## 1. The 30-second full check

One command runs the whole automated suite, core plus all three harness adapters:

```console
$ python -m pytest tests adapters/mcp/tests adapters/telegram/tests adapters/hermes_agent/tests
...
NNN passed, 2 skipped   ← your count will vary; anything failed/errored is a stop
```

**Green means:** the ledger, routing, corrections, ingest, the HTTP endpoints, and
all three agent harnesses passed their end-to-end contracts. The 2 skips are the
live-LLM smokes (they need an API key, see §7). If this is green, you can stop
here; the sections below are for verifying a specific surface by hand.

---

## 2. Core loop (CLI)

`skip` only accepts the suggested idea and shows a look. **build it** (or “the
scatter one” on the bake log) is what installs:

```console
$ H=$(mktemp -d)
$ domain-foundry --home $H init
Initialized …  ledger.sqlite schema_version=9  domains.sqlite schema_version=1
$ domain-foundry --home $H new-domain "i have a log of sourdough bakes" --reply skip --reply "build it"
… "domain": "sourdough" … "state": "test_drive"
$ domain-foundry --home $H capture "baked a 75% hydration country loaf, came out great"
… "status": "applied", "routed": [ { "domain": "sourdough", "confidence": 0.95 } ]
$ domain-foundry --home $H query --domain sourdough
… 1 row
$ domain-foundry --home $H correct "that sunday batard was 78 not 72"
… "action": "amend", "applied": true, "eval_case_id": "ec_…"
$ domain-foundry --home $H health
… "ok": true
```

To walk the looks step instead of `--reply skip --reply "build it"`:

```console
$ domain-foundry --home $H new-domain "i have a log of sourdough bakes"
… "state": "fork"
$ domain-foundry --home $H wizard reply <session> "i want to data visualize all my bakes"
… "state": "looks"
$ domain-foundry --home $H wizard reply <session> "the scatter one"
… "state": "test_drive"
```

**Verify:** capture routes to `sourdough` and is `applied`; the correction returns
an `eval_case_id` (the fix became a regression test); health is `ok`.

---

## 3. Bolt-on ingestion

Prove the "pull in existing notes" path is non-destructive and idempotent:

```console
$ NOTES=$(mktemp -d); mkdir -p $NOTES/baking
$ echo "baked a 75% hydration country loaf, came out great" > $NOTES/baking/a.md
$ echo "milk, eggs, coffee"                   > $NOTES/shopping.md

$ domain-foundry --home $H ingest $NOTES --dry-run     # preview, writes nothing
… "scanned": 2, "captured": 0, "by_domain": { "sourdough": 1 }, "unfiled": 1

$ domain-foundry --home $H ingest $NOTES               # pull in
… "scanned": 2, "captured": 2

$ domain-foundry --home $H ingest $NOTES               # re-run → idempotent
… "captured": 0, "skipped_existing": 2

$ domain-foundry --home $H ingest $NOTES --only sourdough   # one foundry only
… "captured": 0, "filtered_out": 1     # (0 new; shopping.md left untouched)
```

**Verify:** the second run captures nothing new (`skipped_existing`), and your
source files are unchanged (the CI test `tests/unit/test_ingest.py` asserts every
byte is identical after ingest).

---

## 4. MCP harness (Claude Desktop / Cursor)

Automated. Drives the server over real stdio MCP `tools/call`:

```console
$ python adapters/mcp/tests/test_mcp_e2e.py
… MCP E2E OK
```

Live check in Claude Desktop: add the config from
[Connect your agent → MCP](connect-your-agent.md#mcp), restart, and say
*"i have a log of sourdough bakes."* You should see the `domain_foundry_*` tools fire.

---

## 5. Telegram harness

Automated. Runs the whole conversation against a mock Telegram API, no token:

```console
$ python adapters/telegram/tests/test_telegram_bridge.py
Telegram E2E OK
```

Live check: create a bot with @BotFather, then from this checkout
`pip install -e ./adapters/telegram` and
`TELEGRAM_BOT_TOKEN=… domain-foundry-telegram` and text it the bake-log line
(full steps in [Connect your chat app](connect-your-agent.md#telegram)).

---

## 6. hermes-agent harness

Automated. Drives the adapter's real tool surface:

```console
$ python adapters/hermes_agent/tests/test_hermes_e2e.py
… Hermes adapter E2E OK
```

Live check against a running hermes-agent: `scripts/hermes_e2e_smoke.sh` (uses an
isolated profile and a throwaway home; does not touch your default gateway).

---

## 7. Web app + "Add a source"

```console
$ domain-foundry --home $H serve
# open http://127.0.0.1:8787   → Today / Your passions / Inbox / Settings;
#                                Settings → Sources → Preview routing → Pull in
```

**Verify:** the Today feed shows filed/saved badges and a **Wrong?** button per
row; **Settings → Sources** previews routing (writes nothing) then pulls in on
confirm. The local server's write path is available at
`http://127.0.0.1:8787/api/capture`.
---

## 8. Regenerate the proof snapshots

```console
$ python scripts/tutorial_snapshots.py
  ✅ cli  ✅ mcp  ✅ telegram  ✅ hermes
ALL HARNESSES PROVEN ✅
```

Deterministic. Anyone gets byte-identical snapshots under
`docs/tutorial/snapshots/`.

---

## 9. Opt-in: live LLM

To exercise routing with a real model (enables the 2 skipped smokes and makes
off-keyword captures route correctly):

```bash
# DeepSeek (Hermes already has DEEPSEEK_API_KEY if you use that runtime):
export DOMAIN_FOUNDRY_LLM=live
export DEEPSEEK_API_KEY=<your key>
domain-foundry setup --provider deepseek -y --no-probe

# Or any OpenAI-compatible endpoint. OpenRouter GLM-5.2 shown:
export DOMAIN_FOUNDRY_LLM=live
export DOMAIN_FOUNDRY_ROUTINE_BASE_URL=https://openrouter.ai/api/v1
export DOMAIN_FOUNDRY_ROUTINE_API_KEY=<your key>
export DOMAIN_FOUNDRY_ROUTINE_MODEL=z-ai/glm-5.2
export DOMAIN_FOUNDRY_LIVE_SMOKE=1
python -m pytest tests/contract/test_llm_live_smoke.py -q
```

With a live model, `ingest --dry-run` on a mixed notes folder routes off-keyword
notes correctly (e.g. "that sunday batard was 78 not 72" → `sourdough`), not just the
ones containing the domain word.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Off-keyword captures land in Inbox (`unfiled`) | No API key → heuristic router only matches literal keywords | Set a live model (§9); heuristic is keyword-only by design |
| `Address already in use` on `serve` | A previous server is still bound | `lsof -ti:8787 \| xargs kill`, or `serve --port 8788` |
| `pack add` fails after switching homes | A stale `DOMAIN_FOUNDRY_HOME` from a prior run | `unset DOMAIN_FOUNDRY_HOME` or always pass `--home` |
| MCP test can't find the server | `domain-foundry-mcp` not on PATH | The test launches via `python -m`; for Claude Desktop, `pip install -e ./adapters/mcp` from the checkout |
| `POST /api/capture` fails | Check that `domain-foundry serve` is running and, for token-protected binds, send the bearer token | The daemon serves the canonical read/write contract |
| `new-domain … --reply skip` stays in `looks` | `skip` is not install anymore | `wizard reply <session> "build it"` (or `--reply skip --reply "build it"`) |

## What "all green" is

- **Everything passed** across core + three adapters (only the 2 opt-in live-LLM smokes skip).
- All four surfaces (CLI, MCP, Telegram, hermes-agent) proven end-to-end.
- Source files byte-identical after ingest; re-runs idempotent.
- Snapshots regenerate identically.
