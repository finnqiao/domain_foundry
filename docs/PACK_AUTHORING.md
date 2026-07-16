# Pack authoring style guide

This guide is the quality bar the domain-creation wizard (plan §6, P6) applies
when it proposes a provisional pack, and the reference for humans hand-editing
packs. A pack is **data, not code** (ADR-004): six YAML files, no executable
logic. Everything here maps to `pack validate` and the routing eval gate.

## The six files

| File | Purpose |
|---|---|
| `pack.yaml` | Manifest: `name`, `version`, `title`, `description`, `interpretation`, `aliases` |
| `schema.yaml` | Object types → fields (+ optional links) |
| `routing.yaml` | L1 regex rules, ≥8 example utterances, ≥2 negatives, LLM hints |
| `operations.yaml` | Allowed operations per object (`create`/`update`/`correct`/`merge`/`delete`) |
| `policy.yaml` | Apply-policy defaults (auto_apply / review / confirm) + never-drop `fallback` |
| `projections.yaml` | App views (blocks) + optional markdown vault layout |

## Naming & fields

- **snake_case** for pack names, object types, and field names (`bulk_hours`, not `bulkHours`).
- Pack name matches `^[a-z][a-z0-9_]{1,62}$`; keep it short and singular-ish (`sourdough`, `running`).
- Every object needs a `title_field` (the human label) and a datetime field with
  `default: capture_time` when it is time-ordered (enables timeline blocks).
- Prefer the smallest field set that captures the passion; add more later via the
  hardening loop (§6.2) — you never have to get it perfect up front.

## Unit discipline

- Numeric fields **declare a `unit`** (`percent`, `grams`, `km`, `minutes`,
  `hours`, `pages`). Ambiguous quantities are the #1 correction source, so the
  wizard interview asks about units (e.g. hydration in *percent* vs *grams*).
- Add `min`/`max` where a physical range exists (hydration `40–120` percent).

## Enums bias to `allow_other`

- Model small closed vocabularies as `enum` with explicit `values`.
- Set `allow_other: true` unless the set is truly fixed — real life produces a
  value you didn't anticipate, and losing it is worse than an untidy list.

```yaml
result: {type: enum, values: [dense, decent, good, great], allow_other: true}
```

## Events vs regimens

Distinguish a **thing that happened** from a **standing plan** (a lesson from the
private health domain):

- **Event** — a `care_event`, a `bake`, a `run`: timestamped, one row per occurrence.
- **Regimen / entity** — a `plant`, a `starter`: long-lived, updated in place.

Route feeding/observation language to the *event*, acquisition/naming language to
the *entity*. Keep their routing vocabularies **disjoint** so each example matches
exactly one object.

## Routing rules & examples

- Rules are ordered case-insensitive regexes compiled into one L1 matcher.
- Provide **≥8 example utterances** (the wizard emits ~10–12) and **≥2 negatives**
  — sentences that look plausible but must *not* route (dev/admin chatter is ideal).
- Examples should read like real captures and must route to their intended object
  in dry-run. The wizard regenerates with targeted rules if any example misroutes.
- Use `llm_hints` for the one or two disambiguations a reader would need
  ("hydration is baker's percentage"; "feeding activity is the starter, not a bake").

## Policy

Start permissive but safe:

```yaml
defaults:
  - {operation: create, min_confidence: 0.8,  action: auto_apply}
  - {operation: update, min_confidence: 0.85, action: auto_apply}
  - {operation: correct, action: auto_apply}
  - {operation: delete, action: review}
fallback: unfiled_card
```

Set `create` to `confirm` only for genuinely sensitive domains — the wizard's
privacy question drives this.

## Evolution

Every schema change goes through a migration (§5.7). The hardening loop turns a
plain-language edit ("add a crumb_photo field") into an `ALTER TABLE` migration,
a `schema_registry` refresh, and an appended routing fixture. Generated and
hand-edited packs stay migratable forever because they share this one path.
