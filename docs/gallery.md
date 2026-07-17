# Pack gallery

Every pack below is **data only** ([ADR-004](adr/ADR-004-packs-are-data.md)),
authored purely through the public six-file pack format, and ships with
synthetic fixtures. Install any of them with `domain-foundry pack add packs/<name>`.

## Bundled reference packs

### :material-food-fork-drink: `food` — the deep showcase

The "look how deep a pack can go" pack. It models the full
concept→recipe→experiment→observation lifecycle across five linked objects
(`idea` → `recipe` → `cook` → `dining` → `observation`) and demonstrates
lifecycle-transition `update` operations. **32 committed routing fixtures**
replay 100% green.

```bash
domain-foundry pack add packs/food
domain-foundry capture "cooked a batch of shoyu ramen, came out great"
```

### :material-map-marker-path: `travel` — cross-domain links

Trips / timeline items / bookings-lite with **synthetic places only** ("Port
City", "River Station", "Old Town"). Demonstrates open-context hints (the
`active` trip as default owner), a `planner` block, and **cross-domain links**
(`dining ↔ trip`) into `food.dining`. **31 committed fixtures** replay 100%
green; four of them fan out into two linked domains.

```bash
domain-foundry pack add packs/travel
domain-foundry capture "dinner at River Station Grill, then heading to Port City in March"
```

### :material-flower: `plants` — the beginner pack

Watering / repotting / observations for houseplants. Events (`care_event`) vs
entities (`plant`) done cleanly, with a care-log timeline, a grouped plant list,
faceted search, and activity stats. This is the pack the
[remix-in-an-afternoon tutorial](tutorial-plant-care.md) builds from scratch.

```bash
domain-foundry pack add packs/plants
domain-foundry capture "watered the monstera, soil still damp"
```

### :material-bread-slice: `sourdough` — the wizard archetype

The canonical single-event domain (`bake`): hydration, flour mix, crumb result.
Doubles as the wizard's "sourdough journey" golden archetype.

```bash
domain-foundry pack add packs/sourdough
domain-foundry capture "baked a 75% hydration country loaf, came out great"
```

## Starter template

`packs/_template/` is the empty skeleton — the six YAML files with the required
keys and nothing else. Copy it (or run the wizard) to start a new domain.

```bash
cp -r packs/_template packs/mydomain
$EDITOR packs/mydomain/schema.yaml
domain-foundry pack validate mydomain
```

Or let the wizard generate one from a sentence:

```bash
domain-foundry new-domain "I want to track my climbing sessions"
```

## Community-candidate list

These are good first community packs — small, well-scoped passions that fit the
events-vs-entities model cleanly. **Not yet shipped**; they are ideas for
contributors (see [Contributing](../CONTRIBUTING.md) and the pack-submission
issue template).

| Candidate | Core object(s) | Notes |
|---|---|---|
| `running` | `run` (event) | distance/pace/route; a wizard archetype already. |
| `reading` | `book` (entity) + `session` (event) | pages/rating; entity-vs-event practice. |
| `coffee` | `brew` (event) | dose/ratio/method; unit discipline showcase. |
| `climbing` | `session` (event) + `route` (entity) | grade enums with `allow_other`. |
| `garden` | `bed` (entity) + `task` (event) | seasonal; complements `plants`. |
| `workouts` | `workout` (event) | sets/reps; a wizard archetype already. |
| `birding` | `sighting` (event) | species + location; enum `allow_other` is essential. |
| `practice` | `session` (event) | instrument practice minutes + focus area. |

To propose one, open a **pack submission** issue with the manifest, ≥8 routing
examples, and ≥2 negatives; a pack must pass `pack validate` and its own routing
dry-run to be listed.
