# Roamboard sync adapter (Phase 7 — shadow-ready)

Import Roamboard feed / pending-patch shapes into DomainFoundry **travel**
objects via an **in-process** `HarnessAPI` (same pattern as the hermes-agent
`LocalHarnessClient`). Shadow mode diffs private `travel.sqlite` (read-only)
against DF under `{DF_HOME}/shadow/roamboard/`.

**This adapter does not cut over production.** Old Roamboard launchd agents stay
enabled; the 7-day zero-diff gate and launchd flip remain manual.

## What it does

| Mode | Behavior |
|---|---|
| `--dry-run` (default) | Reconcile feed → would_import counts; no DF writes |
| `--apply` | Idempotent upsert on `source_ref` (`roamboard:trip:…`, `roamboard:timeline_item:…`, `roamboard:event:…` / `roamboard:patch:…`) |
| `--shadow` | Dry-run accounting + write `shadow/roamboard/<UTC>/diff.json` + `SUMMARY.md` comparing private travel.sqlite (RO) vs DF |

Hard constraints:

- Never mutates `travel/data/travel.sqlite` (opened `file:…?mode=ro` only).
- Never disables / rewrites Roamboard launchd plists.
- No secrets in repo — live pull uses env vars only.

## Enablement

```bash
# From a domain_foundry checkout / worktree:
export DOMAIN_FOUNDRY_HOME=~/HermesWorkspace/foundry-dry   # or any DF home
export PYTHONPATH=$PWD/core:$PWD/adapters/roamboard/src

# 1) Shadow dry-run against a canned feed (safe; no private writes):
domain-foundry --home "$DOMAIN_FOUNDRY_HOME" roamboard sync \
  --shadow \
  --feed tests/fixtures/roamboard/feed.json \
  --travel-db ~/HermesWorkspace/travel/data/travel.sqlite

# 2) Apply fixture feed into DF (still does not touch travel.sqlite):
domain-foundry --home "$DOMAIN_FOUNDRY_HOME" roamboard sync \
  --apply \
  --feed tests/fixtures/roamboard/feed.json

# 3) Push preview only (builds a feed from DF; does NOT POST to Roamboard):
domain-foundry --home "$DOMAIN_FOUNDRY_HOME" roamboard export-feed -o /tmp/df-roamboard-feed.json
```

### Optional live pull (skipped without creds)

| Env | Purpose |
|---|---|
| `ROAMBOARD_SYNC_TOKEN` | Bearer for pending-patches / sync API |
| `ROAMBOARD_SYNC_URL` | Default `https://roamboard.vercel.app/api/sync/hermes` |
| `ROAMBOARD_SUPABASE_URL` | Optional Supabase REST base |
| `ROAMBOARD_SUPABASE_KEY` | Optional Supabase anon/service key |

Live smoke tests are opt-in and skip when these are unset.

## Cutover (manual — not performed by this adapter)

1. Run nightly `--shadow` for **≥7 consecutive zero-diff days** (trips + timeline
   items + slug parity; event_log count diffs are soft).
2. Freeze private writers → delta re-import → flip launchd sync job → unfreeze.
3. Rollback = reload the old launchd job; leave `travel.sqlite` frozen RO.

Until that gate passes, keep the private Hermes ↔ Roamboard path as
writer-of-record.
