# End-to-end testing runbook

**Who this is for:** anyone verifying that Domain Foundry works — a contributor
before a PR, a maintainer before a release, or you, kicking the tires after
install. **Time:** 2 minutes for the automated pass, ~15 for the full manual sweep.

Every command below is copy-paste and shows the output you should see. If a step's
output matches, that surface works.

!!! note "One rule"
    Nothing here touches real data. Every command uses a throwaway `--home` or a
    temp workspace, and the router runs in **heuristic** mode (no API key, fully
    deterministic) unless you opt into a live model.

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

One command runs the whole automated suite — core plus all three harness adapters:

```console
$ python -m pytest tests adapters/mcp/tests adapters/telegram/tests adapters/hermes_agent/tests
...
219 passed, 2 skipped, 1 warning
```

**Green means:** the ledger, routing, corrections, ingest, the HTTP endpoints, and
all three agent harnesses passed their end-to-end contracts. The 2 skips are the
live-LLM smokes (they need an API key — see §7). If this is green, you can stop
here; the sections below are for verifying a specific surface by hand.

---

## 2. Core loop (CLI)

```console
$ H=$(mktemp -d)
$ domain-foundry --home $H init
Initialized …  ledger.sqlite schema_version=8  domains.sqlite schema_version=1
$ domain-foundry --home $H new-domain "track my bouldering sessions" --reply skip
… "domain": "bouldering" … "state": "test_drive"
$ domain-foundry --home $H capture "good bouldering session, felt strong"
… "status": "applied", "routed": [ { "domain": "bouldering", "confidence": 0.95 } ]
$ domain-foundry --home $H query --domain bouldering
… 1 row
$ domain-foundry --home $H correct "actually that felt moderate, not hard"
… "action": "amend", "applied": true, "eval_case_id": "ec_…"
$ domain-foundry --home $H health
… "ok": true
```

**Verify:** capture routes to `bouldering` and is `applied`; the correction returns
an `eval_case_id` (the fix became a regression test); health is `ok`.

---

## 3. Bolt-on ingestion

Prove the "pull in existing notes" path is non-destructive and idempotent:

```console
$ NOTES=$(mktemp -d); mkdir -p $NOTES/climbing
$ echo "good bouldering session, felt strong" > $NOTES/climbing/a.md
$ echo "milk, eggs, coffee"                   > $NOTES/shopping.md

$ domain-foundry --home $H ingest $NOTES --dry-run     # preview, writes nothing
… "scanned": 2, "captured": 0, "by_domain": { "bouldering": 1 }, "unfiled": 1

$ domain-foundry --home $H ingest $NOTES               # pull in
… "scanned": 2, "captured": 2

$ domain-foundry --home $H ingest $NOTES               # re-run → idempotent
… "captured": 0, "skipped_existing": 2

$ domain-foundry --home $H ingest $NOTES --only bouldering   # one foundry only
… "captured": 0, "filtered_out": 1     # (0 new; shopping.md left untouched)
```

**Verify:** the second run captures nothing new (`skipped_existing`), and your
source files are unchanged (the CI test `tests/unit/test_ingest.py` asserts every
byte is identical after ingest).

---

## 4. MCP harness (Claude Desktop / Cursor)

Automated — drives the server over real stdio MCP `tools/call`:

```console
$ python adapters/mcp/tests/test_mcp_e2e.py
… ### capture { "status": "applied", "domain": "bouldering" }
… MCP E2E OK — 8 steps
```

Live check in Claude Desktop: add the config from
[Connect your agent → MCP](connect-your-agent.md#mcp), restart, and say
*"track my bouldering sessions."* You should see the `domain_foundry_*` tools fire.

---

## 5. Telegram harness

Automated — runs the whole conversation against a mock Telegram API, no token:

```console
$ python adapters/telegram/tests/test_telegram_bridge.py
👤 /new track my bouldering climbing sessions
🤖 🎉 *bouldering* is live. …
👤 good bouldering session at the gym, felt strong
🤖 ✅ Logged to *bouldering* (entry).
Telegram E2E OK
```

Live check: create a bot with @BotFather, then
`TELEGRAM_BOT_TOKEN=… domain-foundry-telegram` and text it (full steps in the
[Telegram adapter README](https://github.com/finnqiao/domain_foundry/tree/main/adapters/telegram#readme)).

---

## 6. hermes-agent harness

Automated — drives the adapter's real tool surface:

```console
$ python adapters/hermes_agent/tests/test_hermes_e2e.py
… Hermes adapter E2E OK
```

Live check against a running hermes-agent: `scripts/hermes_e2e_smoke.sh` (uses an
isolated profile and a throwaway home; does not touch your default gateway).

---

## 7. Web app + "Add a source" page

```console
$ domain-foundry --home $H serve
# open http://127.0.0.1:8787   → capture feed with routing badges;
#                                "Add a source" in the sidebar → Preview routing → Pull in
```

**Verify:** the capture feed shows `applied`/`unfiled` badges and a **Wrong?**
button per row; the **Add a source** view previews routing (writes nothing) then
pulls in on confirm. The HTTP write path is intentionally sealed — `curl -X POST
http://127.0.0.1:8787/api/capture` returns **410 Gone** by design.

---

## 8. Regenerate the proof snapshots

```console
$ python scripts/tutorial_snapshots.py
  ✅ cli  ✅ mcp  ✅ telegram  ✅ hermes
ALL HARNESSES PROVEN ✅
```

Deterministic — anyone gets byte-identical snapshots under
`docs/tutorial/snapshots/`.

---

## 9. Opt-in: live LLM

To exercise routing with a real model (enables the 2 skipped smokes and makes
off-keyword captures route correctly):

```bash
# Any OpenAI-compatible endpoint. OpenRouter GLM-5.2 shown:
export DOMAIN_FOUNDRY_LLM=live
export DOMAIN_FOUNDRY_ROUTINE_BASE_URL=https://openrouter.ai/api/v1
export DOMAIN_FOUNDRY_ROUTINE_API_KEY=<your key>
export DOMAIN_FOUNDRY_ROUTINE_MODEL=z-ai/glm-5.2
export DOMAIN_FOUNDRY_LIVE_SMOKE=1
python -m pytest tests/contract/test_llm_live_smoke.py -q
```

With a live model, `ingest --dry-run` on a mixed notes folder routes off-keyword
notes correctly (e.g. "sent a V5 on the overhang" → `bouldering`), not just the
ones containing the domain word.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Off-keyword captures land in `unfiled` | No API key → heuristic router only matches literal keywords | Set a live model (§9); heuristic is keyword-only by design |
| `Address already in use` on `serve` | A previous server is still bound | `lsof -ti:8787 \| xargs kill`, or `serve --port 8788` |
| `pack add` fails after switching homes | A stale `DOMAIN_FOUNDRY_HOME` from a prior run | `unset DOMAIN_FOUNDRY_HOME` or always pass `--home` |
| MCP test can't find the server | `domain-foundry-mcp` not on PATH | The test launches via `python -m`; for Claude Desktop, `pipx install domain-foundry-mcp` |
| `POST /api/capture` returns 410 | Not a bug — HTTP writes are disabled | Drive writes through the CLI, MCP, or `/sources`; reads (`/api/query`) work over HTTP |

## What "all green" is

- **219 passed / 2 skipped** across core + three adapters.
- All four surfaces (CLI, MCP, Telegram, hermes-agent) proven end-to-end.
- Source files byte-identical after ingest; re-runs idempotent.
- Snapshots regenerate identically.
