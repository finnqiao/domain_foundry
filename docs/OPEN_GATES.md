# Open gates (human / time)

In-repo convergence work is landed on the integration branch. These items
**cannot** be finished by an agent alone.

| # | Gate | How | Blocker |
|---|---|---|---|
| 1 | SOTA backlog triage → `needs_review < 20` | `HermesWorkspace/scripts/triage_backlog.py` (or `tools/`) | Needs `ANTHROPIC_API_KEY` (DeepSeek is wrong tier) |
| 2 | Live vault reproject `--apply` | Snapshot under `backups/phase2/` already; dry-run clean | Explicit OK to mutate `~/HermesWorkspace/obsidian_vault` |
| 3 | Geocode proposal review → `--apply` | `tools/geocode_venues.py`; proposal JSON/CSV under backups/docs | Human confirm per venue |
| 4 | Enable mesh flags + Telegram QA | `HERMES_MESH_FAST_PATH=1`, `HERMES_MESH_OUTBOUND=1` | Manual QA; defaults stay OFF |
| 5 | Japanese + food cutover | Freeze → delta import → flip classify | Human cutover window |
| 6 | ≥7-day Roamboard shadow → launchd flip | `scripts/roamboard_shadow_nightly.sh` | Calendar time; do not flip launchd early |
| 7 | Production week + overlay move + release | `LAUNCH_CHECKLIST.md`; move personal packs to overlay | Lived week; no force-push/tag without ask |

## Ready to run locally (no production flip)

```bash
# Founder aggregates (counts only) from foundry-dry
DOMAIN_FOUNDRY_HOME=~/HermesWorkspace/foundry-dry \
  python /path/to/domain_foundry/scripts/founder_metrics.py

# Weekly Concierge triage nudge (idempotent)
domain-foundry --home ~/HermesWorkspace/foundry-dry mesh weekly-triage

# Roamboard shadow one night (records streak file; no launchd)
DOMAIN_FOUNDRY_HOME=~/HermesWorkspace/foundry-dry \
  DOMAIN_FOUNDRY_REPO=/path/to/domain_foundry \
  ./scripts/roamboard_shadow_nightly.sh

# History leakscan (no rewrite)
python scripts/leakscan.py --history
```

See also: [`MESH_AS_BUILT.md`](MESH_AS_BUILT.md), [`RETIREMENT_RUNBOOK.md`](RETIREMENT_RUNBOOK.md),
[`PRIVATE_OVERLAY.md`](PRIVATE_OVERLAY.md), [`LAUNCH_CHECKLIST.md`](../LAUNCH_CHECKLIST.md).
