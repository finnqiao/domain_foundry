# Phase status

Tracking implementation of `docs/OPEN_SOURCE_HARNESS_PLAN.md`.

| Phase | Status | Notes |
|---|---|---|
| P0 Bootstrap & guardrails | **Done** | Fresh repo, MIT, ADRs, CI, leakscan, substrate DDL, migration runner |
| P1 Core substrate | **Done** | capture/query/health, HarnessAPI, FastAPI, CLI, attachments, contract tests |
| P2 Packs & routing | **Done** | Pack loader/compiler, L1/L2 router, cost guard, heuristic/cassette LLM, eval gate ≥90% |
| P3 Apply & corrections | **Done** | ApplyEngine, journal, policy, CanonicalChangeExecutor, correct/review APIs, few-shot + eval_case |
| P4 Projections & review API | **Done** | ProjectionCoordinator (outbox/drain/watermarks/retry + serve loop), managed-region markdown adapter, direct-query block data, projection lag in health, receipts pending→refreshed, enriched review queue (filters/diffs/bulk/SLO) |
| P5 App shell | **Done** | Vite+React SPA served from FastAPI static mount; nine built-in blocks + registry; global surfaces (home/capture feed/review queue/health); detail provenance chain; correction dialogs (amend/move/merge/undo/mark-wrong); custom-block side-load + in-app docs; teaching empty states |
| P6 Domain wizard | **Done** | Wizard engine (goal→interview→generate→validate→dry-run→test-drive→hardening), resumable sessions, archetype+generic proposal generator, `new_domain`/`wizard_reply` API, CLI `new-domain` + `wizard reply`, HTTP endpoints, pack authoring style guide |
| P7 Eval framework | **Done** | Cassette drift + `--live-llm`; frozen-clock audit (lint+test); full scoring (routing/field/disposition/calibration) + per-pack scorecards + committed baseline + regression diff; `eval backfill`/`eval export --sanitize`; PR replay gate + nightly live-LLM stub; curated contract-case set |
| P8 Demo & reference packs + hermes-agent adapter | **Done** | `food` + `travel` packs (authored purely through the public pack format), each with ≥25 green routing fixtures incl. cross-domain dining↔trip links; hermes-agent plugin (`register(ctx)` + `plugin.yaml` + skill fragment + `hermes_agent.plugins` entry point) with a live-stack conformance test; quickstart + automated clean-machine gate; founder friction-log checklist |
| P9 Docs & launch | Not started | |

## P3 gate evidence

- Approve → apply exactly once (double-resolve + crash-between recovery)
- One-message correction round-trip: capture → NL amend → revision + supersession + `correction_event` + `eval_case` + fewshot bank
- Merge leaves no orphan canonical rows (FK clean)
- Policy matrix: auto_apply / review / confirm × confidence + user overrides

## P4 gate evidence

- **Kill-the-daemon convergence** (`tests/contract/test_projection_convergence.py`): canonical commit with the drain loop down → receipt `pending`, outbox `pending`, no watermark → restart (fresh `HarnessAPI`) → `drain_projections()` converges every adapter → outbox `done`, per-adapter watermark advances on each new commit, receipt flips to `refreshed`, managed markdown note materialized. Failed adapter leaves the row `pending`/`failed` and a healthy coordinator retries from durable state.
- **Managed-region fuzz** (`tests/contract/test_managed_region_fuzz.py`): 300 randomized user edits outside the markers always survive re-render; managed regions update in place; new sections append without touching free zones; on-disk write→hand-edit→re-render round-trip preserves user free text.
- **Review SLO counters accurate** (`tests/contract/test_review_slo.py`): pending / overdue / oldest-age counts correct against aged fixtures; proposed-vs-canonical diff previews; bulk approve drains the queue to zero.
- **Projection lag in health + block data** (`tests/unit/test_projections.py`): health reports pending depth + oldest age + per-adapter watermarks; direct-query timeline/list/stats bindings; `mark_dirty` coalesces pending rows.
- **HTTP surface + serve loop** (`tests/contract/test_api.py::test_p4_endpoints_and_drain_loop`): FastAPI lifespan starts/stops the background drain loop cleanly; `/api/blocks/*`, `/api/review/stats`, `/api/projections/drain` respond.
- Full suite green: **43 passed** (`python -m pytest`). `ruff check core tests scripts` clean. `python scripts/leakscan.py` OK. `pyright` clean on all P4 modules.

## P5 gate evidence

- **Scripted walkthrough on synthetic data** (`tests/contract/test_app_shell.py`): install two packs (`sourdough` + `plants` via `/api/packs/activate`) → capture from the web box (`POST /api/capture`, routes to `sourdough.bake`, `applied`) → see it in **timeline / search / stats / history / planner** (`/api/blocks/<view>/data`, all nine blocks exercisable against the synthetic packs) → open the **detail view** (`/api/objects/<domain>/<object_type>/<uid>`) with the full provenance chain (capture text → interpretation confidence → revisions) → **correct** from detail (amend hydration 75→80 via `/api/correct`, no privileged write) → **revision chain visible** (new `object_revision` with `hydration: 75 → 80`) → **review queue drains to zero** (`/api/review` diffs + `/api/review/bulk-resolve` + SLO counters) → **health panel green** (`/api/health`: ledger/domains integrity ok, projection lag 0, LLM spend under cap, on-demand routing score).
- **Real-browser confirmation** (headless Chrome, live `domain-expert serve`): the same walkthrough was driven through the built SPA end-to-end — empty-state home → install domains → capture receipt with routing badges → capture feed → domain tabs (Bakes/Find/Progress/History/Plan/Starters) → detail modal with provenance → correction dialog applies hydration 75→80 and the new revision renders in the provenance panel → review queue clear with SLO counters → health cards all green (routing score 94%) → in-app custom-block docs. No visual glitches or console errors.
- **Security posture:** API binds `127.0.0.1` by default; non-local bind refuses to start without `DOMAIN_EXPERT_API_TOKEN` (bearer-gated, `test_api.py::test_non_local_bind_requires_token`). Block data stays read-only + parameterized (unknown/unsafe fields rejected). The shell is a pure API client — every mutation goes through `capture()` / `correct()` / review endpoints.
- **Lighthouse note (skipped):** a full Lighthouse perf run needs a headless-Chrome + CI budget this box does not carry, so the P5 gate is met via the API+DOM contract test (`test_app_shell.py`) plus the SPA `tsc` typecheck + `vite build`. The bundle is lean (~72 kB gzipped JS, ~4 kB gzipped CSS), responsive (single-column ≤820px), and keyboard-friendly (Esc closes modals, ⌘/Ctrl+Enter captures, tablist nav) as a lightweight stand-in.
- Full suite green: **66 passed** (`python -m pytest`) incl. 4 new app-shell contract tests. `ruff check core tests scripts` clean. `python scripts/leakscan.py` OK. Frontend `npm run build` (tsc + vite) green.

## P6 gate evidence

- **Cold start to working domain** (`tests/contract/test_wizard.py::test_cold_start_gate`): one-sentence goal → interview (≤6 targeted questions) → `skip` accepts defaults → generate → `pack validate` → dry-run routing → **activate** → a real `capture()` routes into the freshly generated `sourdough` domain, and driving a capture through `wizard_reply` returns a verbose routing explanation + instant-correct affordance.
- **≥10 golden goal-statements** (`test_golden_goal_generates_valid_routing_pack`, incl. "sourdough journey"): 12 goals each produce a pack that passes full validation and routes its own examples **100%** in dry-run (threshold ≥95%). Archetypes (sourdough/running/reading/coffee/workouts) + generic activity-log fallback for anything else. HeuristicProvider only — no live LLM.
- **Hardening round-trips with a migration** (`test_hardening_edit_round_trips_with_migration`): NL edit "add a crumb_photo field" → pack diff preview (nothing applied) → `confirm` → `ALTER TABLE` migration written to the pack + executed against `domains.sqlite` (column now exists), `schema_registry` refreshed, pack still validates, and a routing fixture/eval case appended. Rename + cancel path covered (`test_hardening_rename_and_cancel`).
- **Resumable + channel-agnostic** (`test_session_is_resumable`): a fresh `HarnessAPI` (new process) resumes a persisted session by id and completes it. Same engine drives CLI (`domain-expert new-domain`), HTTP (`POST /api/wizard`, `POST /api/wizard/{id}/reply`), and any runtime adapter.
- **Repeated-correction hook** (§8.4): `wizard_suggest(domain)` surfaces a hardening suggestion once a reason-code is corrected ≥3×.
- Also fixed a latent P2 router crash (`new_ulid` imported conditionally inside `_persist` but used on the unfiled never-drop path) that any unroutable capture could trigger; hoisted the import. This unblocked 4 previously-red P5 app-shell tests.
- Full suite green: **66 passed** (`python -m pytest`). `ruff check core tests scripts` clean. `python scripts/leakscan.py` OK. Wizard modules pyright-clean (remaining pyright warnings are pre-existing `int(cur.lastrowid)` casts in P2 `router.py`).

## P7 gate evidence

- **Deliberately-breakable regression path** (`tests/contract/test_eval_regression.py::test_break_then_restore_regression`): score the pristine synthetic corpus → committed baseline; mutate one **sourdough** fixture's expected `operation` so routing misses → `diff_baseline` reports `has_regression` with the legible per-pack line `sourdough: routing_accuracy 0.886 -> …`, and the drop is **isolated to that pack** (`plants` unaffected); restore the fixture → green. This is the "break a heuristic on a branch → CI fails with a per-pack diff; restore → green" gate (§10.3).
- **Full scoring + scorecards** (`test_eval_scoring.py`): routing accuracy, per-field precision/recall/F1, disposition accuracy, and confidence-bucket **calibration curves** per pack; overall + per-pack scorecards serialized to a compact committed baseline (`examples/synthetic/eval_baseline.json`, 65 cases, routing 0.938, **0 false-completed-action cases**). Fresh replay diffs clean against the committed baseline (the PR gate).
- **False-completed-action = release-blocking at zero** (`test_zero_false_completed_actions_on_negatives`, `test_false_completed_action_is_release_blocking`): every negative case is checked for any real-domain `auto_apply` span (zero across the corpus); an injected count of 1 fails the baseline diff.
- **Cassette store**: normalized prompt-hash keys, `replay`/`record`/`live` modes; `live` mode re-records and accumulates a **drift report** (recorded-vs-live diffs) surfaced via `eval --live-llm`. Deterministic replay over the heuristic inner keeps the PR gate free and reproducible.
- **Frozen-clock audit** (`scripts/clock_audit.py` + `tests/unit/test_clock_audit.py`): bans bare `datetime.now()`/`datetime.utcnow()`/`time.time()`/`time.monotonic()` anywhere under `core/` except the injectable clock provider (`clock.py`); the audit is green today and the guard-the-guard test proves it catches an injected violation. Wired as a CI step.
- **Correction→corpus backfill** (`eval backfill`, `test_backfill_creates_eval_cases_from_pre_p3_corrections`): synthesizes `eval_case` rows from pre-P3 `correction_event` rows that lack them (expected = corrected `right_json`, input = original capture text); idempotent (re-runs create nothing new); `--dry-run` supported.
- **Sanitized export** (`eval export --sanitize`, `test_export_sanitizes_pii`): strips secrets + PII (email/URL/phone/handle/IP/home-paths) from correction-derived cases and emits contribution-ready JSONL plus a redaction report for the human diff-review step (§10.4).
- **Curated contract-case set** (`tests/contract/test_curated_contract.py`): the five named invariants — approval-executes-exactly-once, never-drop ladder, multi-domain fan-out, idempotent re-capture, projection convergence — collected as one self-contained gate that runs alongside the corpus replay (§10.1/§10.3).
- **CI wiring**: `.github/workflows/ci.yml` adds a frozen-clock audit step and an **eval corpus replay regression gate** (`domain-expert eval --full --min-accuracy 0.9`, fails on any per-pack regression or false-completed-action increase vs the committed baseline). `.github/workflows/nightly-eval.yml` is the on-demand/scheduled **live-LLM** job against a **pinned model** (`gpt-4o-mini`, bumping is a reviewed change), uploads a drift-report artifact, degrades gracefully without an API key, and documents the release gate (zero false-completed-action cases + pinned-model replay + leak scan).
- Full suite green: **82 passed** (`python -m pytest`, +16 P7 tests). `ruff check core tests scripts` clean. `python scripts/clock_audit.py` OK. `python scripts/leakscan.py` OK. New P7 modules (`evals/*`, cassette provider, CLI, audit script) are pyright-clean (remaining pyright errors are pre-existing `int(cur.lastrowid)` casts in P2/P3 modules).

## P8 gate evidence

- **Food demonstration pack** (`packs/food/`, `tests/contract/test_demo_packs.py`): the full concept→recipe→experiment→observation lifecycle across five linked objects (`idea` → `recipe` → `cook` → `dining` → `observation`), authored entirely through the public six-file pack format (no core changes needed — dogfood gate clean). `pack validate food` OK; **32 committed routing fixtures** (`packs/food/evals/fixtures.jsonl`, ≥25) replay **100%** green (create + lifecycle-transition `update` operations + negatives) with the deterministic heuristic router.
- **Travel reference pack** (`packs/travel/`): trips / timeline items / bookings-lite generalized from the private travel domain with **synthetic places only** ("Port City", "River Station", "Old Town" — no real names copied). Demonstrates open-context hints (the `active` trip as the default owner, via `llm_hints`), a `planner` block, and **cross-domain links (dining↔trip)** into `food.dining`. `pack validate travel` OK; **31 committed fixtures** (≥25) replay **100%** green with `food`+`travel` active, and the four cross-domain fixtures each fan out into two linked domains.
- **Both packs are data-only** (ADR-004) and did not require any core capability to be added — validated through `pack validate` and the routing replay, same path as the wizard and the bundled `plants`/`sourdough` packs. They live outside the default corpus/`eval_baseline.json`, so the P7 PR regression gate is unaffected.
- **hermes-agent adapter** (`adapters/hermes_agent/`): installable `domain-expert-hermes-agent` package with a `register(ctx)` entry point published on the `hermes_agent.plugins` group (`pyproject.toml`), a declarative `plugin.yaml`, and seven tools (`capture` / `query` / `correct` / `review_list` / `review_resolve` / `new_domain` / `wizard_reply`) mapped onto the `domain-expert serve` HTTP surface via a thin injectable client. Capture-first behavioral guidance shipped as a documented skill fragment (`SKILL.md`, also exported as `CAPTURE_FIRST_GUIDANCE`). Supported hermes-agent range **`>=0.4,<0.7`** pinned in the README + `SUPPORTED_HERMES_AGENT`.
- **Adapter conformance test** (`tests/contract/test_hermes_agent_adapter.py`): a scripted **capture → query → correct → review** session runs through the adapter's tools against a live in-process FastAPI stack (Starlette `TestClient`); the NL correction (`hydration 75 → 80`) is confirmed durable via the read surface; `register(ctx)` wires all seven tools + injects the guidance; version range asserted. (+4 tests)
- **Quickstart + clean-machine gate**: `docs/QUICKSTART.md` covers `pipx`/editable install → `init` → `pack add` → capture → `serve` → optional hermes-agent hookup. `scripts/quickstart_gate.sh` automates the pack-install + single-domain + cross-domain capture path against a throwaway `--home` using only the public CLI (green). The manual browser/agent slice is documented for the 15-minute gate.
- **Founder-as-user-0**: `docs/FOUNDER_VALIDATION.md` is the private friction-log process checklist (cold-start ≥2 real domains → test-drive → correct → harden → live-in-it → file synthetic-repro issues). Personal packs/data are never committed; `leakscan.py` is the backstop. Public CI proves the mechanism on synthetic corpora; the lived validation is run privately.
- Full suite green: **90 passed** (`python -m pytest`, +8 P8 tests). `ruff check core tests scripts adapters` clean. `python scripts/leakscan.py` OK. `python scripts/clock_audit.py` OK. New packs + adapter contain **synthetic data only** (PII/real-remote scan clean).

## Quick commands

```bash
domain-expert init
domain-expert pack add packs/plants
domain-expert pack add packs/sourdough
domain-expert pack add packs/food            # P8 demo pack (concept→recipe→experiment→observation)
domain-expert pack add packs/travel          # P8 reference pack (trips/timeline/bookings + dining↔trip links)
scripts/quickstart_gate.sh                    # automated clean-machine gate (pack install + capture path)
pip install ./adapters/hermes_agent          # P8 hermes-agent plugin (hermes_agent.plugins entry point)
domain-expert capture "baked a 75% hydration country loaf"
domain-expert correct "that bake was 80% hydration not 75"
domain-expert review list
domain-expert review stats
domain-expert projections drain
domain-expert eval                          # deterministic cassette replay (routing gate)
domain-expert eval --full                   # per-pack scorecards + regression diff vs baseline
domain-expert eval --full --update-baseline # rewrite committed baseline snapshot
domain-expert eval --full --live-llm --no-baseline  # nightly: re-record + drift report
domain-expert eval backfill                 # pre-P3 corrections -> eval_case rows
domain-expert eval export --out contrib.jsonl --sanitize  # PII-stripped contribution

# P6 — guided domain creation
domain-expert new-domain "I want to track my sourdough journey" \
  --reply skip \
  --reply "baked a country loaf at 80% hydration" \
  --reply "add a crumb_photo field" \
  --reply confirm
domain-expert wizard reply <session_id> "fed the rye starter"
```
