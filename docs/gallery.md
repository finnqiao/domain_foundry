# Passion gallery

The **[idea atlas](concepts/idea-atlas.md)** is the library of what’s out there
(topics and app ideas). Bundled packs are **compiled outcomes**, analogs you
can install in one shot when you already know you want the kitchen-sink version.

Saying “food” in create-a-domain does **not** dump the Food Lab pack. It opens
the food neighborhood (recipes vs nutrition vs dining). `pack add food` remains
the explicit “install everything” analog.

```bash
domain-foundry atlas search "food"
domain-foundry pack add food          # analog: install the showcase pack
```

## Bundled analogs

### :material-food-fork-drink: `food`

Kitchen-sink analog: recipes, cooks, dining, observations. Use it when you want
the full Food Lab, not when you only said “food”.

```bash
domain-foundry pack add food
domain-foundry capture "cooked a batch of shoyu ramen, came out great"
```

### :material-map-marker-path: `travel`

Trips, timeline items, and light bookings with **synthetic places only**
("Port City", "River Station", "Old Town"). Can link a dinner into `food`.

```bash
domain-foundry pack add travel
domain-foundry capture "dinner at River Station Grill, then heading to Port City in March"
```

### :material-flower: `plants`

Watering, repotting, and plant notes. A good first passion, and also the subject of the
[remix-in-an-afternoon tutorial](tutorial-plant-care.md).

```bash
domain-foundry pack add plants
domain-foundry capture "watered the monstera, soil still damp"
```

### :material-bread-slice: `sourdough`

Bakes: hydration, flour mix, crumb. The default activation demo.

```bash
domain-foundry pack add sourdough
domain-foundry capture "baked a 75% hydration country loaf, came out great"
```

### :material-ideogram-cjk: `japanese`

Vocab / grammar review sessions (local quiz shell). Fixture-backed; live calendar
and provider behavior remain human gates.

```bash
domain-foundry pack add japanese
```

### Also bundled

| Name | Notes |
|---|---|
| `health` | Fitness / labs / supplements-style objects (genericized demo) |
| `dev` | Developer scratch passion |
| `x_radar` | Experimental; prefer a private overlay for personal variants |

## Starter template

`packs/_template/` is the empty skeleton. Copy it (or run the wizard):

```bash
cp -r packs/_template packs/mydomain
$EDITOR packs/mydomain/schema.yaml
domain-foundry pack validate mydomain
```

Or describe a passion in one sentence:

```bash
domain-foundry new-domain "I want to track my climbing sessions"
```

## Ideas for contributors (not bundled yet)

| Candidate | Shape | Notes |
|---|---|---|
| `running` | `run` | distance/pace/route |
| `reading` | `book` + `session` | pages/rating |
| `coffee` | `brew` | dose/ratio/method, and the wizard can scaffold this today |
| `climbing` | `session` + `route` | grade enums with `allow_other` |
| `garden` | `bed` + `task` | seasonal; complements `plants` |
| `workouts` | `workout` | sets/reps |
| `birding` | `sighting` | species + location |
| `practice` | `session` | instrument minutes + focus |

Held-out synthetic packs for `coffee` and `climbing` live under
`examples/heldout/packs/` for evals. They are not installed by
`pack add coffee` / `pack add climbing`.

To propose one, open a **pack submission** issue with the manifest, ≥8 routing
examples, and ≥2 negatives; it must pass `pack validate` and its own routing
dry-run to be listed.
