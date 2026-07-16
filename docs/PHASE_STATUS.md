# Phase status

Tracking implementation of `docs/OPEN_SOURCE_HARNESS_PLAN.md`.

| Phase | Status | Notes |
|---|---|---|
| P0 Bootstrap & guardrails | **Done** | Fresh repo, MIT, ADRs, CI, leakscan, substrate DDL, migration runner |
| P1 Core substrate | **Done** | capture/query/health, HarnessAPI, FastAPI, CLI, attachments, contract tests |
| P2 Packs & routing | **Done (skeleton)** | Pack loader/validator/compiler, L1+L2 router, cost guard, heuristic/cassette LLM, eval gate ≥90% |
| P3 Apply & corrections | Not started | |
| P4 Projections & review API | Not started | |
| P5 App shell | Scaffold only | Vite+React capture box; nine blocks registry stub |
| P6 Domain wizard | Not started | |
| P7 Eval framework | Skeleton in P2 | Full scoring/calibration/export in P7 |
| P8 Packs & hermes-agent adapter | Partial | `plants` + `sourdough` synthetic packs; food/travel demo packs TBD |
| P9 Docs & launch | Not started | |

## P2 gate evidence

- Routing eval: **60/65 (92.3%)** on `examples/synthetic/routing_eval.jsonl` (≥60 cases, ≥90% required)
- Multi-domain fan-out writes ≥2 `change_request` rows + `object_link`
- Cost guard trips when daily cap exceeded (rules/heuristic fallback)
- CLI: `pack list|validate|add|new`, `eval`

## Quick commands

```bash
domain-expert init
domain-expert pack add packs/plants
domain-expert pack add packs/sourdough
domain-expert capture "watered the monstera and baked a 75% loaf"
domain-expert eval
```
