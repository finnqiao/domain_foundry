# Tutorial: remix in an afternoon

Build a **plant-care** domain from scratch — the same pack that ships as
`packs/plants/`, reconstructed step by step. By the end you will have a working
domain that routes real captures, renders app views, and accepts corrections.
Budget: an afternoon, most of it thinking about your schema.

You can either **hand-author** the six YAML files (this tutorial) or let the
**wizard** generate a first draft (`domain-foundry new-domain "…"`) and edit from
there. Doing it by hand once makes the wizard output obvious.

## 0. Prerequisites

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
domain-foundry init
```

## 1. Model the domain (the only hard part)

Ask two questions about plant care:

1. **What happens repeatedly?** Watering, repotting, fertilizing, pruning,
   observing. Each is a timestamped **event** → one object: `care_event`.
2. **What persists?** The plants themselves — long-lived, updated in place. That
   is an **entity** → a second object: `plant`.

Keeping events and entities separate (with **disjoint** routing vocabularies) is
the single most important modeling decision. See
[events vs entities](concepts/packs.md#objects-events-vs-entities).

Start a pack from the template:

```bash
cp -r packs/_template packs/plants
```

## 2. `pack.yaml` — the manifest

```yaml
name: plants
version: 0.1.0
title: "Plant Care"
description: "Track watering, repotting, and observations for houseplants."
author: "you"
license: MIT
core_compat: ">=0.1,<2"
interpretation: simple
aliases: [plant, houseplants]
```

`interpretation: simple` says most captures are single-object and L1 regex will
usually be enough — no LLM tokens for the common case.

## 3. `schema.yaml` — objects and fields

```yaml
objects:
  care_event:
    title_field: plant_name
    fields:
      plant_name: {type: text, required: true}
      action: {type: enum, values: [water, fertilize, repot, prune, mist, observe], allow_other: true}
      noted_at: {type: datetime, required: true, default: capture_time}
      soil_moisture: {type: enum, values: [dry, damp, wet], allow_other: true}
      notes: {type: text, long: true}
  plant:
    title_field: plant_name
    fields:
      plant_name: {type: text, required: true}
      species: {type: text}
      location: {type: text}
      status: {type: enum, values: [thriving, ok, struggling, dormant], allow_other: true}
```

Notes on the choices:

- Every object has a **`title_field`** (the human label).
- `care_event` has a datetime with **`default: capture_time`** so timeline blocks
  work automatically.
- Enums set **`allow_other: true`** — real life produces a value you didn't list,
  and losing it is worse than an untidy vocabulary.

## 4. `routing.yaml` — rules, examples, negatives

L1 rules are ordered case-insensitive regexes; a match nominates an object and a
confidence boost. Route action verbs to the **event**, and acquisition/naming to
the **entity**.

```yaml
rules:
  - {match: "(water(?:ed|ing)?|soak(?:ed)?|irrigat)", object: care_event, confidence_boost: 0.1}
  - {match: "(repot(?:ted|ting)?|new\\s+pot)", object: care_event, confidence_boost: 0.1}
  - {match: "(fertiliz|feed(?:ing)?\\s+the\\s+plant|nutrient)", object: care_event, confidence_boost: 0.08}
  - {match: "(prune|trimmed|mist(?:ed)?)", object: care_event, confidence_boost: 0.05}
  - {match: "(monstera|pothos|ficus|snake\\s+plant|fern|succulent|houseplant)", object: care_event, confidence_boost: 0.08}
  - {match: "(new\\s+plant|bought\\s+a|added\\s+a)[:\\s]+\\w+", object: plant, confidence_boost: 0.15}

examples:
  - {text: "watered the monstera, soil still damp", expect: {object: care_event, operation: create, fields: {plant_name: monstera, action: water, soil_moisture: damp}}}
  - {text: "repotted the pothos into a bigger pot", expect: {object: care_event, operation: create, fields: {action: repot}}}
  - {text: "fertilized the ficus this morning", expect: {object: care_event, operation: create, fields: {action: fertilize}}}
  - {text: "pruned yellow leaves on the zz plant", expect: {object: care_event, operation: create, fields: {action: prune}}}
  - {text: "misted the calathea after dry air", expect: {object: care_event, operation: create, fields: {action: mist}}}
  - {text: "snake plant looks thriving on the sill", expect: {object: care_event, operation: create}}
  - {text: "bought a new monstera for the living room", expect: {object: plant, operation: create, fields: {plant_name: monstera}}}
  - {text: "houseplant checkup — pothos needs water", expect: {object: care_event, operation: create, fields: {plant_name: pothos, action: water}}}

negative_examples:
  - {text: "the app build is toast"}
  - {text: "deploy the release candidate tonight"}
  - {text: "merge the feature flag behind a gate"}

llm_hints: >
  Care events are timestamped actions. Prefer care_event over plant unless the
  message is clearly about acquiring or naming a plant.
```

Two rules of the road, both enforced by `pack validate`:

- **≥8 examples**, each must route to its intended object in dry-run.
- **≥2 negatives** — plausible-looking sentences that must *not* route (dev/admin
  chatter is perfect). These stop over-eager rules.

## 5. `operations.yaml` and `policy.yaml`

```yaml
# operations.yaml
care_event: [create, update, correct, delete]
plant: [create, update, correct, merge, delete]
```

```yaml
# policy.yaml — permissive but safe
defaults:
  - {operation: create, min_confidence: 0.8, action: auto_apply}
  - {operation: update, min_confidence: 0.85, action: auto_apply}
  - {operation: correct, action: auto_apply}
  - {operation: delete, action: review}
  - {operation: merge, action: review}
fallback: unfiled_card
```

The `fallback: unfiled_card` is never-drop in action: anything that doesn't route
becomes an unfiled card you can triage, not silence.

## 6. `projections.yaml` — the app views

```yaml
app:
  icon: "🪴"
  views:
    - {id: care,   title: "Care log", block: timeline, object: care_event, config: {date_field: noted_at}}
    - {id: plants, title: "Plants",   block: list,     object: plant,      config: {group_by: status}}
    - {id: find,   title: "Find",     block: search,   objects: [care_event], config: {facets: [action, soil_moisture]}}
    - {id: history,title: "History",  block: history,  object: care_event, config: {date_field: noted_at, period: week}}
    - {id: stats,  title: "Activity", block: stats,    object: care_event, config: {measures: [{field: action, agg: distribution}]}}
markdown:
  folder: "Plants"
```

Block data is compiled from your schema, so adding a field later automatically
makes it available to columns, facets, and measures. See
[Custom blocks](CUSTOM_BLOCKS.md) for the full block catalog.

## 7. Validate, dry-run, activate

```bash
domain-foundry pack validate plants     # schema + routing example/negative coverage
domain-foundry pack add packs/plants     # activate it
```

`pack validate` is offline and total — no LLM, no data touched. Fix anything it
flags (a misrouting example, too few negatives) before moving on.

## 8. Capture for real

```bash
domain-foundry capture "watered the monstera, soil still damp"
domain-foundry capture "bought a new monstera for the living room"
domain-foundry query --domain plants
domain-foundry serve   # open http://127.0.0.1:8787 and browse Care log / Plants / Find
```

The first routes to `care_event`; the second to `plant`. Because the
vocabularies are disjoint, L1 resolves both with zero tokens.

## 9. Correct, then harden

Fix a mistake in one message — the canonical record updates and history is kept:

```bash
domain-foundry correct "that wasn't the monstera, it was the pothos"
```

Then grow the schema through the hardening loop instead of hand-editing SQL:

```bash
domain-foundry new-domain --harden plants   # e.g. "add a photo field"
```

A plain-language edit becomes a diff preview → an `ALTER TABLE` migration → a
`schema_registry` refresh → an appended routing fixture. Your pack stays
migratable forever.

## Where to go next

- Tighten routing with more examples and negatives ([routing](concepts/routing.md)).
- Add golden `evals/fixtures.jsonl` so your pack has its own regression gate
  ([evaluation replay](concepts/replay.md)).
- Contribute it: open a **pack submission** issue (see the
  [gallery](gallery.md#community-candidate-list) and
  [Contributing](https://github.com/finnqiao/domain_foundry/blob/main/CONTRIBUTING.md)).
