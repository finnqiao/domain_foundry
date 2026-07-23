# Mesh as-built (convergence)

**Status:** Implemented on `feat/phase1-substrate-hardening` (OSS) + private
gateway flags (default **OFF**). Design source:
[`PER_DOMAIN_AGENT_MESH_2026-07-20.md`](PER_DOMAIN_AGENT_MESH_2026-07-20.md).

## What shipped

| Piece | Location | Notes |
|---|---|---|
| Inbox journal + domain inbox | `core/.../mesh/journal.py`, `inbox.py` | Capture-first; kill-9 survival tested |
| Concierge | `mesh/concierge.py` | Route → enqueue; stickiness / barge-in / not_mine / switch (env flags) |
| Domain Experts | `mesh/expert.py` | Serial per domain; in-process `HarnessAPI` |
| Supervisor | `mesh/supervisor.py` | Child registry; `mesh register` / `mesh status` |
| Outbound queue | `mesh/outbound.py` + `ledger_006` | Durable; private poller gated |
| Sessions + schedules | `mesh/sessions.py`, `schedules.py` | Quiz 09:00; weekly triage |
| Observability / DLQ | `mesh/observability.py` | `mesh dlq list\|retry`; `/api/mesh/*` |
| Weekly triage nudge | `mesh/triage_nudge.py` | `domain-foundry mesh weekly-triage` |
| Private fast path | `~/.hermes/plugins/logbook/mesh_*.py` | `HERMES_MESH_FAST_PATH` default OFF |
| Private outbound | same | `HERMES_MESH_OUTBOUND` default OFF |

## Operator cheat-sheet

```bash
export DOMAIN_FOUNDRY_HOME=~/HermesWorkspace/foundry-dry   # or production home
domain-foundry mesh status
domain-foundry mesh dlq list
domain-foundry mesh weekly-triage          # once per ISO week
domain-foundry mesh register japanese
domain-foundry mesh register food
```

## Still human / private

- Enable fast path + outbound only after Telegram QA.
- Japanese + food cutover (freeze → delta → flip classify) — see
  [`OPEN_GATES.md`](OPEN_GATES.md).
- Retirement of `~/.hermes/plugins/logbook` classify/store — see
  [`RETIREMENT_RUNBOOK.md`](RETIREMENT_RUNBOOK.md). Do **not** disable live
  without confirmation.
