# User stories, and the evidence behind each

Every story below is written from the user's side, paired with the command that
serves it and the **reproducible evidence** that it works. Where something is
unproven, that is stated as unproven rather than left implied.

Reproduce the whole table:

```bash
scripts/quickstart_gate.sh     # onboarding + capture + import lifecycle
scripts/release_audit.sh       # leakscan · clock · ruff · pytest · docs · eval replay
pytest                         # 281 passed / 2 skipped
```

---

## 1. "I've never done this before. Walk me through it."

**Story.** I don't know what a model tier is, I'm not sure which API key I have,
and I don't want to read a config reference before I can write down my first
note.

**What serves it.** `domain-foundry setup` with no arguments. It asks which
provider you have a key for, suggests a model for each tier, proves the key
works, then asks what you want to do first — and runs that step for you.

```console
$ domain-foundry setup
Domain Foundry needs a model to route captures. You bring the key.

  *1. Anthropic (Claude)
      One key covers both tiers.
   2. OpenAI
   3. DeepSeek
   ...
Which provider? [1]:

Two tiers. Routine handles every capture; sota handles the calls
that rewrite a record or change a schema.
  routine model [claude-haiku-4-5]:
  sota model [claude-opus-5]:

Checking each tier can reach its model:
  routine  claude-haiku-4-5             ok — reachable
  sota     claude-opus-5                ok — reachable

Where do you want to start?
  1. Start from a ready-made log (food, plants, sourdough, travel)
  2. Describe a log in your own words and have one built
  3. Pull in notes you already have (a folder, an Obsidian vault)
  4. Attach a structured source (SQLite table, JSON/JSONL export)
```

**Evidence.**

| Claim | How it's proved |
|---|---|
| The flow completes and installs a working pack | Driven with piped answers end-to-end; `pack add food` runs and prints the next command to try |
| A declined key is never written to disk | `test_key_is_not_written_by_default` — asserts the secret is absent from the file and that `api_key_env` is recorded instead |
| A stored key is not world-readable | `test_stored_key_is_chmod_600` |
| `_template` is not offered as a starting point | Filtered in `cli.py`; it is pack-author scaffolding and a dead end for a newcomer |
| A capture is never lost even with no model at all | `--provider none` → `mode = "heuristic"`, and a capture still routes to `food` by keyword rules and applies |

---

## 2. "I know exactly what I want. Don't ask me anything."

**Story.** I have a dotfile with my keys. I want this configured in one
non-interactive command, in a script, on a fresh machine, and I do not want a
new config file becoming the source of truth for settings I already manage.

**What serves it.**

```bash
domain-foundry setup --provider anthropic --sota claude-opus-5 -y --no-probe
domain-foundry setup --show     # what resolved, and from where
```

Settings resolve **env > config file > provider default**. An install that
predates the config file behaves identically; exported variables always win.

**Evidence.**

| Claim | How it's proved |
|---|---|
| Env beats the config file | `test_env_beats_config_file`; also asserted live in `quickstart_gate.sh` (`DOMAIN_FOUNDRY_SOTA_MODEL=claude-sonnet-5` overrides a written config) |
| Config beats the registry default | `test_config_file_beats_registry_default` |
| An env-only install still works with no config file at all | `test_legacy_env_only_install_still_works` |
| A hand-broken config does not brick the CLI | `test_malformed_config_does_not_brick_the_cli` — malformed TOML falls back to env/defaults instead of raising on every command |
| `--show` never leaks a key | `test_resolved_status_never_leaks_a_key` |

---

## 3. "I already have a database. Let me bring it and keep working."

**Story.** Three years of entries live in a SQLite table with my own column
names. I want them in here without exporting to Markdown first, without a
migration script I have to maintain, and **without any risk to the original**.

**What serves it.** `domain-foundry import` — a short YAML maps source rows to a
domain's objects; dry-run is the default.

```bash
# preview: where would every row land? writes nothing
domain-foundry import -m my_mapping.yaml --sqlite ~/old-app.sqlite

# your table isn't named like the mapping entity? remap it, and filter
domain-foundry import -m my_mapping.yaml --sqlite ~/old-app.sqlite \
    --table entries=journal_entries --where entries="deleted_at IS NULL"

domain-foundry import -m my_mapping.yaml --json ~/export/ --apply
```

**Evidence.**

| Claim | How it's proved |
|---|---|
| Your database is not modified, even by `--apply` | sha256 of the source file captured before and after a successful 2-row `--apply`: **identical**. Opened via a `file:…?mode=ro` URI |
| Re-running does not duplicate | Full lifecycle asserted in `quickstart_gate.sh`: dry-run `would_import=8` → `--apply` `imported=8` → re-apply `skipped_existing=8` |
| A partial import cannot pass quietly | Every row is classified imported / skipped / failed, and the command **exits non-zero** unless `accounted_for == source_total`. Verified: importing into a workspace without the target pack reports `failed=4` with `no pack installed for domain 'japanese'` and exits 1 |
| Skips are explained per row | `--markdown` prints e.g. `hermes:travel:trip:3 (skipped_invalid): missing required fields: name` |
| A table name cannot be injected | `SqliteTableSource` rejects non-identifier table names before interpolation |

This is the path three years of real Hermes data was migrated on.

---

## 4. "I keep notes in Obsidian / a folder. Layer on top, don't replace it."

**Story.** My notes are already where I want them. I want structure derived from
them, not a new place to type.

**What serves it.** `domain-foundry ingest` — read-only, idempotent, dry-run
first, with `--watch` to keep pulling in new notes. Non-terminal users get the
same engine behind **Add a source** in the app.

```bash
domain-foundry ingest ~/Notes --dry-run       # preview routing, writes nothing
domain-foundry ingest ~/Notes --only bouldering
domain-foundry ingest ~/logs/journal.log --split lines
domain-foundry ingest ~/Notes --watch
```

**Evidence.** Idempotency is on `(channel, source_ref)`, so a re-scan captures
only what changed; covered by `tests/unit/test_ingest.py` and the
[testing runbook](tutorial/testing-runbook.md) §3. Nothing at the source is
moved, renamed, or edited. Write-back to a vault is a separate, opt-in,
managed-region-only path (`projections reproject --vault`, dry-run by default).

---

## 5. "Spend my money on the calls that matter."

**Story.** Most of what I write is unambiguous. I don't want a frontier model
priced for every trivial capture — but when it's a correction, or it's rewriting
a schema, I want the good model.

**What serves it.** Two tiers, with automatic escalation.

| Tier | Handles | Shape |
|---|---|---|
| `routine` | every capture's routing + field extraction | high volume, low stakes |
| `sota` | corrections, structural/schema ops, low confidence, multi-domain fan-out | rare, high stakes |

Escalation (`select_model_tier`) fires when a routing rule declares `tier: sota`,
on any update/delete/merge/correct operation, on correction-shaped text, on
`no_match`/`multi_pack`, or below 0.7 confidence. A daily cost guard caps spend
(`DOMAIN_FOUNDRY_DAILY_COST_CAP`, default `$0.25`) with per-tier sub-caps.

**Evidence.**

| Claim | How it's proved |
|---|---|
| The request shape is right per model, not per provider | `test_sampling_param_support_per_model` (9 models). Haiku 4.5 *accepts* `temperature` but *rejects* `output_config.effort`; Opus 5 is the reverse |
| An unknown model degrades safely | `test_unknown_model_gets_the_conservative_shape` — a model newer than the table gets no sampling params and no optional extras |
| A rejected optional parameter doesn't fail the capture | `test_400_retries_without_optional_params` |
| An auth failure isn't retried pointlessly | `test_401_does_not_retry` — and the error stays one readable line |
| Spend is metered per tier | `tests/unit/test_llm_tiering.py` — token-derived cost against the pricing table, per-tier caps enforced |

> ⚠️ **Unproven:** the per-model request-shape table is encoded from the
> published API contract and unit-tested against a mocked transport, but has
> **never been executed against a real key** — no credential was available in the
> build environment. A wrong row is a 400, and a 400 is invisible (see story 6).
> One live `setup --probe` per provider settles it; tracked as a human gate in
> [`LAUNCH_CHECKLIST.md`](https://github.com/finnqiao/domain_foundry/blob/main/LAUNCH_CHECKLIST.md) §1.
> The **failure** path *is* proved end-to-end: a bad key yields
> `HTTP 401: invalid x-api-key` on both tiers.

---

## 6. "Tell me when it's broken. Don't quietly do worse."

**Story.** The failure I fear most is the silent one — where it looks like it's
working and isn't.

**Why this needed explicit work.** Domain Foundry catches LLM failures into the
keyword heuristic so a capture is never lost. That is the right behaviour, and it
has a nasty consequence: **a misconfigured model looks exactly like "no key set
yet"** — captures keep succeeding, just with worse routing. Three real bugs hid
there, and none of them presented as an error.

**What serves it.**

- `setup` probes each tier with one cheap live call, so a bad key fails at setup
  rather than at every capture.
- A capture that tried a model and failed carries `llm_error` on the receipt and
  prints a warning; it is never conflated with an unconfigured install.

```console
$ domain-foundry capture "cooked shoyu ramen, came out great"
  ...
  "llm_error": "LLMError: Anthropic LLM failed: HTTP 401: invalid x-api-key"
warning: model routing failed (…) — captured with keyword rules only.
```

**Evidence.**

| Claim | How it's proved |
|---|---|
| Completing setup actually changes the capture path | `test_config_mode_live_reaches_the_capture_path` — regression for a bug where a finished setup still routed on keyword rules until `DOMAIN_FOUNDRY_LLM=live` was separately exported |
| `--home /elsewhere` reads that workspace's config | `test_explicit_home_reads_that_workspaces_config`, `test_router_threads_its_workspace_home` |
| Setup can't claim success without a reachable key | `test_is_already_configured_gates_the_interview` — a *named but unset* env var no longer counts as a credential |
| A failed model call is visible, not swallowed | End-to-end: stored-but-invalid key → `llm_error` on the receipt + CLI warning, capture still kept and routed by rules |
| Nothing configured still means no spend | `test_no_config_and_no_env_stays_heuristic` |

---

## Gate summary

| Gate | Result |
|---|---|
| `pytest` | **288 passed / 2 skipped** (2 skips are opt-in live-LLM smokes) |
| `ruff check core tests scripts adapters` | clean |
| `pyright` | **0 errors** |
| `scripts/release_audit.sh` | **9/9 PASS** — leakscan · clock audit · no tracked DBs · history starts at P0 · ruff · pyright · pytest · mkdocs build · eval corpus replay |
| `scripts/quickstart_gate.sh` | PASS — onboarding write, env override, single- and cross-domain capture, import lifecycle |
| GitHub Actions `ci` + `leakscan` | green |

### What clearing the last red gate turned up

`ci` had been red since 2026-07-17 on 45 Pyright errors, and
`release_audit.sh` ran ruff and pytest but **not** Pyright — so the local gate
reported 8/8 over a failing CI for twelve days. Two consequences were worse than
the type errors themselves:

- **Pyright runs before pytest in the workflow**, so the test suite had not
  actually run in CI for those twelve days either.
- **The adapter E2E tests gated nothing.** `testpaths` was `["tests"]`, so the
  MCP / Telegram / hermes-agent proofs under `adapters/*/tests/` were never
  collected by a bare `pytest` or by CI — the same three proofs that had once
  been green on a no-op. They are in `testpaths` now, which is where the jump
  from 281 to 287 tests comes from.

Turning the gates green surfaced **three real bugs that no green local run could
have shown**, each in a different blind spot:

| Bug | Why it was invisible |
|---|---|
| `capture_hints.py` called `NominatimClient()` with no argument, but the constructor requires a cache — `TypeError` on every call, inside `except Exception: return out`. Setting `DOMAIN_FOUNDRY_GEOCODE_ON_CAPTURE=1` never geocoded anything and never said so. | Nothing exercised the opt-in path. Caught by the type checker; now has two regression tests that assert coordinates actually land, not merely that nothing raised. |
| The **wheel shipped with no web app** despite `stage_webapp.sh` staging it and the wheel target declaring the artifact. `python -m build` builds the wheel *from the sdist*, and the sdist target did not declare it. | The existing test asserted only that a string appeared in `pyproject.toml` — config text, not outcome. Replaced with a test that builds the real distributions and opens the archive; confirmed it fails when the sdist artifact is removed. |
| `adapters/mcp` declared an unbounded `mcp>=1.2.0`, but `server.py` imports `mcp.server.fastmcp.FastMCP`, which the 2.x line moved. A fresh resolve takes 2.0.0 and the server won't start — so **`pipx install domain-foundry-mcp` was broken for anyone installing today**. | The local venv held 1.28.1, so every local run passed. Only a clean-resolve environment can see version skew between a developer's venv and a new user's install. Capped at `<2`. |

The failure mode they share is the one this project keeps rediscovering: the thing
that hides a bug is usually a broad `except`, a test that asserts configuration
instead of outcome, or an environment that differs from a new user's.

Structural fixes so these cannot go quiet again: `pyright` is a blocking step in
`release_audit.sh` (the local gate can no longer be weaker than the merge gate);
the adapter E2E proofs are in `testpaths` and CI editable-installs the adapters so
the MCP proof's **subprocess** resolves (`pythonpath` alone cannot reach a child
process); `pyright.extraPaths` matches `pytest.pythonpath`; and CI's `ruff` now
covers `adapters` like the audit script does.

Still human gates: the 90-second demo GIF, an external security pass, a lived
production week, and one live `setup --probe` per documented provider.

### PyPI

All five names are **available and unclaimed** as of 2026-07-29:
`domain-foundry`, `domain-foundry-core`, `domain-foundry-mcp`,
`domain-foundry-telegram`, `domain-foundry-hermes-agent`. Distributions build
clean and `twine check` passes on both; the wheel is verified to contain the SPA
and all nine reference packs. Publishing needs a PyPI token, which is a human
step.
