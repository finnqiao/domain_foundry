# Phase status

Tracking implementation of `docs/OPEN_SOURCE_HARNESS_PLAN.md`.

| Phase | Status | Notes |
|---|---|---|
| P0 Bootstrap & guardrails | **Done (skeleton)** | Fresh repo, MIT, ADRs, CI, leakscan, substrate DDL, migration runner |
| P1 Core substrate | **Done (walking skeleton)** | capture/query/health, HarnessAPI, FastAPI, CLI, attachments, contract tests |
| P2 Packs & routing | Not started | Pack loader, L1/L2 router, eval skeleton |
| P3 Apply & corrections | Not started | |
| P4 Projections & review API | Not started | |
| P5 App shell | Scaffold only | Vite+React capture box; nine blocks registry stub |
| P6 Domain wizard | Not started | |
| P7 Eval framework | Not started | |
| P8 Packs & hermes-agent adapter | Stubs only | `_template` pack; food/travel placeholders |
| P9 Docs & launch | Not started | |

## P0/P1 gate evidence

- `pytest` — 17/17 green
- `ruff check core tests scripts` — clean
- `python scripts/leakscan.py` — OK
- `domain-expert init` creates both DBs; integrity+FK checks pass
- Capture-first, idempotent re-capture, secret redaction, FTS query covered by contract tests
