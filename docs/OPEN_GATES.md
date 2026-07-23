# Open gates (human / time)

In-repo convergence work is landed on the integration branch. Local applyable
gates were executed 2026-07-23 (see `CONVERGENCE_LOG.md`). Remaining items need
calendar time or live Telegram.

| # | Gate | Status | Notes |
|---|---|---|---|
| 1 | SOTA backlog triage → `needs_review < 20` | **Done** | OpenRouter `z-ai/glm-5.2`; 260/260 applied; `needs_review=0`; entries still 297. Backup: `backups/phase0/triage-openrouter-*` |
| 2 | Live vault reproject `--apply` | **Done** | Snapshot `backups/phase2/vault-live-before-apply-*`; applied 1119 creates; `unmanaged_ok=true` |
| 3 | Geocode proposal → `--apply` | **Done (partial)** | 14/40 venues confirmed+applied into `foundry-dry`; 26 left (no OSM hit / bad OCR query) |
| 4 | Enable mesh flags + Telegram QA | **Open** | `HERMES_MESH_FAST_PATH` / `HERMES_MESH_OUTBOUND` still default OFF — needs live channel QA |
| 5 | Japanese + food cutover | **Open** | Freeze → delta → flip classify — human cutover window |
| 6 | ≥7-day Roamboard shadow → launchd flip | **Day 1 zero-diff (2026-07-23)** | Travel imported into foundry-dry via `roamboard sync --apply` (222/222: 28 trips / 166 items / 28 events; idempotent rerun = 0 new). Shadow `zero_diff (trips+items+slugs): True`; event_log 815-vs-28 remains a soft diff by design. Streak-regex bug in `roamboard_shadow_nightly.sh` fixed (could never record zero-diff); streak log now shows `2026-07-23 zero-diff`. Run nightly with `ROAMBOARD_FEED=~/HermesWorkspace/travel/exports/json/roamboard-feed.json`. **Do not flip launchd until ≥7 consecutive zero-diff days.** |
| 7 | Production week + overlay move + release | **Open** | Lived week; no tag/push without ask |

## Ran locally (no production flip)

```bash
# Triage (OpenRouter GLM 5.2)
python ~/HermesWorkspace/scripts/triage_backlog.py --propose --provider openrouter --model z-ai/glm-5.2
python ~/HermesWorkspace/scripts/triage_backlog.py --approve-all && python …/triage_backlog.py --apply

# Vault + geocode + shadow + weekly nudge — already executed against foundry-dry / live vault
```

See also: [`MESH_AS_BUILT.md`](MESH_AS_BUILT.md), [`RETIREMENT_RUNBOOK.md`](RETIREMENT_RUNBOOK.md),
[`PRIVATE_OVERLAY.md`](PRIVATE_OVERLAY.md), [`LAUNCH_CHECKLIST.md`](../LAUNCH_CHECKLIST.md).
