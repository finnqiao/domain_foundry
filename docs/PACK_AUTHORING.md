# Pack authoring style guide

Start with an **[idea atlas](concepts/idea-atlas.md) node and its jobs**, then
compile (or hand-write) the six YAML files. The empty `_template` pack is the
second stop, not the first: decide *where in the world of practice this sits*
and *which jobs it is* (catalog, event log, map, gallery, improvement…) before
you name fields.

This guide is the quality bar the domain-creation wizard applies when it
compiles a chosen idea, and the reference for humans hand-editing packs. A pack
is **data, not code** (ADR-004): YAML files, no executable logic. Everything
here maps to `pack validate` and the routing eval gate.

Local atlas overlay: drop YAML in `~/.domain_foundry/atlas/` (same node ids
shadow the shipped graph). Lint with `domain-foundry atlas validate`.

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

## Putting two packs together

Two keys let a pack build on other packs. Both are optional. A pack that uses
neither loads exactly as it did before they existed.

### `extends`: build on another pack

In `pack.yaml`:

```yaml
name: travel_food
extends: travel
```

You get every object, routing rule, operation, and view the parent has, and
they run under your tables, not the parent's. `travel_food` gets its own
`travel_food__trip` table; the travel pack keeps its own.

What happens when both packs say something about the same thing:

| Part | Rule |
|---|---|
| Objects | Both packs' objects are there. If both declare the same object, the fields and links merge and yours win per name. Your `title_field` wins when you set one. |
| Routing rules | Both lists run, yours first. |
| Routing examples and negatives | Both lists, yours first. |
| LLM hints | Yours when you write any, otherwise the parent's. |
| Operations | Merged per object, yours win. |
| Policy | Yours when you write any rows or UI actions, otherwise the parent's. |
| Views | Both lists, yours first. A view id you reuse replaces the parent's. |
| Capabilities | Merged, yours win. |
| Permissions | Both packs' permissions, added together. |
| Agent | Yours when you ship an `agent.yaml`, otherwise the parent's, renamed to your pack. |

One parent only. A loop between packs, such as two packs that extend each
other, is a load error naming both packs.

### `imports`: borrow an object from another pack

```yaml
imports:
  - {from: food, object: dining}
  - {from: food, object: recipe, as: dish}
```

Nothing is copied. The borrowed records stay in the pack that owns them, in
that pack's table. What you get is the right to point at them by a short name.
Use `as` when the name would clash with one of your own objects; a clash you do
not rename is a load error naming your object and the imported one.

### Links become real foreign keys

A link in `schema.yaml` says a record points at one other record:

```yaml
objects:
  timeline_item:
    links:
      dining: {to: food.dining, cardinality: many_to_one}
```

That compiles to a column named after the link with `_uid` on the end, holding
the other record's `object_uid`, plus a foreign key:

```sql
dining_uid TEXT,
FOREIGN KEY (dining_uid) REFERENCES food__dining(object_uid) ON DELETE SET NULL
```

So the database refuses a pointer to a record that is not there, and deleting
the record you point at clears the pointer instead of deleting your record.

If the pack you point at is not installed, your pack still loads and the column
is still there. The foreign key is left off until that pack arrives, because a
constraint pointing at a missing table would make every write fail. The loader
records what you are waiting on, and `pack_conformance.py` prints it under
`composition.waiting_on`.

If the pack you point at *is* installed but has no object by that name, that is
a load error naming your link, the object you asked for, and the objects that
pack really has.

Existing databases only ever gain: applying a pack's schema adds columns that
are missing and never drops or rewrites what is there.

### The `stack` command writes all of this for you

```
domain-foundry stack travel food
```

That writes a `travel_food` pack that extends travel, borrows food's `dining`
object, points travel's `timeline_item` at it, adds one view listing the two
together, and turns the pack on. It then tells you which column carries the
pointer and gives you a capture to try. Use `--objects` to say which objects to
borrow, and `--out` to write the pack somewhere without turning it on.

## Evolution

Every schema change goes through a migration (§5.7). The hardening loop turns a
plain-language edit ("add a crumb_photo field") into an `ALTER TABLE` migration,
a `schema_registry` refresh, and an appended routing fixture. Generated and
hand-edited packs stay migratable forever because they share this one path.
