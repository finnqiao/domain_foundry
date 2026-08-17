# Slice 2 — Travel/Roamboard proves "app"

**Resolution:** medium — designs and endpoint specs are fixed; implementation
details left to the executing dev where marked. Re-read
[`00-OVERVIEW.md`](00-OVERVIEW.md) decisions #1 and #9 before starting.
**Depends on:** Slice 1 complete (new IA, restored writes, Playwright + Vitest
infra, policy-aware receipts).

**Goal (review Gate 3, flagship):** Finn can run a full trip on Foundry under or
instead of Roamboard without loss of utility. The exit is a *filmed vertical
slice* — the app, not a CLI receipt, doing meaningful travel work.

---

## W2.1 Import / reconcile / shadow in the shell

### What already exists (verified 2026-08-10 — reuse, do not rebuild)

- `adapters/roamboard/src/domain_foundry_roamboard/sync.py` —
  `sync_roamboard(...)` (L73) with `SyncMode` (L28: dry-run default / apply /
  shadow), idempotent `source_ref` writes, `SyncReport.to_dict()` (L44);
  `export_df_feed(home, *, limit=500)` (L190) for the reverse direction.
- `shadow.py` — `run_shadow(...)` (L178) comparing the private `travel.sqlite`
  (opened read-only) against DF, producing a `ShadowReport` with a
  `zero_diff` property (L44) and a markdown summary (L270). Nightly wrapper:
  `scripts/roamboard_shadow_nightly.sh` (streak logging already fixed per
  `docs/OPEN_GATES.md` gate 6).
- CLI: `domain-foundry roamboard sync` (`cli.py` L1136) with `--feed`,
  `--patch-bundle`, `--apply`, `--shadow` (dry-run is the default and says so),
  and `roamboard export-feed` (L1206).
- The server-side ingest preview/commit pattern to mirror:
  `POST /api/ingest/preview` + `POST /api/ingest` in
  `core/domain_foundry_core/api/app.py` (~L113–151) — a *local server-side
  operation* driving its own in-process work, which is exactly what a Roamboard
  import is.

### New surface

| Endpoint | Wires to | Notes |
|---|---|---|
| `POST /api/import/roamboard/preview` | `sync_roamboard(mode=SyncMode.DRY_RUN, feed=…)` | Body `{feed_path: str}` (validated: must exist, schemaVersion 2). Returns `SyncReport.to_dict()` — per-row created/updated/skipped/conflict accounting. |
| `POST /api/import/roamboard/commit` | `sync_roamboard(mode=SyncMode.APPLY, …)` | Same body; requires a `preview_token` returned by the preview call (prevents blind commits — same guard style as the ingest pair). |
| `GET /api/import/roamboard/shadow` | latest `ShadowReport` from `{DF_HOME}/shadow/roamboard/` | Read-only; powers the streak widget. |

SPA: **Settings → Sources** gains a Roamboard panel — feed path input,
"Preview import" → reconcile report table (one row per record: outcome, reason),
"Commit" enabled only after preview, and a shadow-streak widget ("7 consecutive
zero-diff days" progress, from the shadow endpoint). Reuse the existing
`Sources.tsx` preview→commit interaction shape.

**Verify:** contract test running preview→commit against a fixture feed
(fixtures exist under `adapters/roamboard`'s tests); idempotency assert (second
commit = all-skipped); Playwright: preview renders the per-row table, commit
requires preview.

## W2.2 Travel workflows in the shell

Extend the declarative block layer **only where travel forces it** (decision #10:
universal shell with deeper declarative capabilities — no per-domain React code).

1. **Itinerary grouping** — `Planner` block gains a pack-declared
   `group_by`/day-bucketing config (travel's `projections.yaml` declares it; the
   block reads it from `BlockData` like `ListBlock` already reads `groups`).
2. **Packing checklist** — a list view with per-item toggles. The toggle is the
   narrow write decision #9 resolved: **new `POST /api/apply`** exposing the
   existing direct-apply path:

   ```
   HarnessAPI.apply_operation(*, domain, operation, object_type,
                              fields=None, object_uid=None, entry_id=None,
                              channel="cli", actor="system")   # harness.py L777
   ```

   Gating (the design constraint that matters): the endpoint accepts only
   operations the pack's `policy.yaml` explicitly declares UI-safe via a new
   `ui_actions:` section, e.g. for travel:

   ```yaml
   # packs/travel/policy.yaml (addition)
   ui_actions:
     - {object_type: packing_item, operation: update, fields: [packed]}
     - {object_type: booking, operation: update, fields: [status]}
   ```

   Anything not declared → 403 with a plain-language message. `channel="web"`,
   `actor="web-ui"` recorded so provenance distinguishes UI actions from
   captures. Current travel policy (`packs/travel/policy.yaml`, quoted in full —
   7 lines) has `defaults` + `fallback: unfiled_card` only; `ui_actions` is a new
   key, ignored by older cores (schema-compiler treats unknown keys per existing
   pack validation — confirm before relying on it).
3. **Map ↔ dining cross-links** — `DetailModal`'s `links` array (currently raw
   UIDs) becomes navigable: clicking a link opens the linked object's detail.
   This is the Slice 1 `?detail=` deep-link mechanism reused, no new server work.
4. **Domain themes** — pack `projections.app` already carries `icon`; add
   optional `accent` (CSS color token override per domain, applied as an inline
   custom property on the domain view root). Keep it to accent + icon; no
   arbitrary theming.
5. **Multi-domain capture fan-out** — already works at the substrate level
   (`scripts/quickstart_gate.sh` proves a dining/travel message fans out).
   Surface it in the Slice 1 receipts translator: "Saved to Travel (dinner
   reservation) and Food (restaurant)".

**Verify:** contract tests for `/api/apply` (declared action succeeds; undeclared
403; provenance recorded); Playwright: toggle a packing item, see it persist
after reload; link-navigation test.

## W2.3 Natural-language reshape with preview / migration / rollback

Reuse `wizard/hardening.py` — `build_plan` (NL edit → structured plan + diff) and
`apply_plan` (writes migration + fixture), already round-tripping in
`tests/contract/test_wizard.py` (~L111).

Add the missing safety half:

- **Snapshot before apply:** pack directory copy + pre-migration table backup to
  `{DF_HOME}/backups/hardening/<timestamp>/` (pack YAML + affected
  `domains.sqlite` tables).
- **`HarnessAPI.hardening_rollback(domain)`** — restores the latest snapshot,
  re-runs `ensure_schemas_applied()`, returns what was restored. Exposed as
  `POST /api/domains/{domain}/rollback`.
- **SPA:** domain Settings tab → "Change this app" conversation → diff card
  (fields added/removed, views changed, migration summary) → confirm → apply →
  receipt with a rollback affordance that remains visible until the next reshape.

**Verify:** contract test: reshape → assert migration applied + snapshot exists →
rollback → assert schema and data restored byte-identical; Playwright: the full
reshape conversation with rollback.

## W2.4 Shadow gate and cutover

- Run the nightly shadow (`scripts/roamboard_shadow_nightly.sh`) until
  **≥7 consecutive zero-diff days** (`ShadowReport.zero_diff`). This is
  `docs/OPEN_GATES.md` gate 6 — a calendar gate; no code can shortcut it.
- Only after the streak: the cutover decision (Foundry under vs instead of
  Roamboard) is a human call, recorded in the convergence log.

## Exit gate

- [ ] Roamboard import runs preview→commit from Settings with a per-row
      reconcile report; second commit is a no-op.
- [ ] Packing/booking toggles work through policy-gated `/api/apply`; undeclared
      operations refused with plain copy; provenance shows `channel="web"`.
- [ ] Itinerary, map, dining, packing, and notes views are cohesive enough to
      run a real trip (filmed vertical slice — the film is the evidence).
- [ ] One NL reshape applied through the diff-preview flow **and rolled back**
      successfully on real data.
- [ ] ≥7 consecutive zero-diff shadow days logged.
- [ ] Zero data-loss incidents across the slice.
