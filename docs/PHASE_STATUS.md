# Phase status

Tracking implementation of `docs/OPEN_SOURCE_HARNESS_PLAN.md`.

| Phase | Status | Notes |
|---|---|---|
| P0 Bootstrap & guardrails | **Done** | Fresh repo, MIT, ADRs, CI, leakscan, substrate DDL, migration runner |
| P1 Core substrate | **Done** | capture/query/health, HarnessAPI, FastAPI, CLI, attachments, contract tests |
| P2 Packs & routing | **Done** | Pack loader/compiler, L1/L2 router, cost guard, heuristic/cassette LLM, eval gate ≥90% |
| P3 Apply & corrections | **Done** | ApplyEngine, journal, policy, CanonicalChangeExecutor, correct/review APIs, few-shot + eval_case |
| P4 Projections & review API | **Done** | ProjectionCoordinator (outbox/drain/watermarks/retry + serve loop), managed-region markdown adapter, direct-query block data, projection lag in health, receipts pending→refreshed, enriched review queue (filters/diffs/bulk/SLO) |
| P5 App shell | Scaffold only | Vite+React capture box; nine blocks registry stub |
| P6 Domain wizard | Not started | |
| P7 Eval framework | Skeleton in P2 | Full scoring/calibration/export in P7 |
| P8 Packs & hermes-agent adapter | Partial | `plants` + `sourdough` synthetic packs; food/travel demo packs TBD |
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

## Quick commands

```bash
domain-expert init
domain-expert pack add packs/plants
domain-expert pack add packs/sourdough
domain-expert capture "baked a 75% hydration country loaf"
domain-expert correct "that bake was 80% hydration not 75"
domain-expert review list
domain-expert review stats
domain-expert projections drain
domain-expert eval
```
