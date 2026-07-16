# Phase status

Tracking implementation of `docs/OPEN_SOURCE_HARNESS_PLAN.md`.

| Phase | Status | Notes |
|---|---|---|
| P0 Bootstrap & guardrails | **Done** | Fresh repo, MIT, ADRs, CI, leakscan, substrate DDL, migration runner |
| P1 Core substrate | **Done** | capture/query/health, HarnessAPI, FastAPI, CLI, attachments, contract tests |
| P2 Packs & routing | **Done** | Pack loader/compiler, L1/L2 router, cost guard, heuristic/cassette LLM, eval gate ≥90% |
| P3 Apply & corrections | **Done** | ApplyEngine, journal, policy, CanonicalChangeExecutor, correct/review APIs, few-shot + eval_case |
| P4 Projections & review API | Not started | Outbox stub enqueued; drain/markdown/SLO in P4 |
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

## Quick commands

```bash
domain-expert init
domain-expert pack add packs/plants
domain-expert pack add packs/sourdough
domain-expert capture "baked a 75% hydration country loaf"
domain-expert correct "that bake was 80% hydration not 75"
domain-expert review list
domain-expert eval
```
