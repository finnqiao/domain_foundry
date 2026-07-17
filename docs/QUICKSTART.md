# Quickstart

Get from a clean machine to a working, captured-into domain in a few minutes,
using only this repo. Target: **under 15 minutes** on a fresh VM (the P8
clean-machine gate). An automated version of the pack-install + capture path is
in [`scripts/quickstart_gate.sh`](../scripts/quickstart_gate.sh).

## 1. Install the core

```bash
pipx install domain-foundry-core          # isolated CLI install
# — or, from a checkout —
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

This puts a `domain-foundry` command on your PATH.

## 2. Initialize the workspace

```bash
domain-foundry init
```

Creates `~/.domain_foundry/` with the two SQLite databases (`ledger.sqlite`,
`domains.sqlite`) and applies substrate migrations.

## 3. Add a demonstration pack

Packs are **data** — no code. Two showcase packs ship in `packs/`:

```bash
domain-foundry pack add packs/food     # cooking ideas → recipes → cooks → dining → learnings
domain-foundry pack add packs/travel   # trips → timeline items → bookings (+ dining↔trip links)
domain-foundry pack validate food
domain-foundry pack validate travel
```

(You can also start with `packs/plants` or `packs/sourdough`.)

## 4. Capture

```bash
domain-foundry capture "cooked a batch of shoyu ramen, came out great"
domain-foundry capture "dinner at River Station Grill and heading to Port City in March"
domain-foundry query --domain food
```

The first routes to `food.cook`; the second fans out into a `food.dining` record
**and** a `travel.trip`, linked across domains.

## 5. Serve the app

```bash
domain-foundry serve
# open http://127.0.0.1:8787
```

Capture from the web box, browse the domain tabs (Cooks / Recipes / Ideas /
Dining / Trips / Timeline / Bookings), open a detail view for the provenance
chain, and correct from there.

## 6. (Optional) Hook up hermes-agent

Let an agent capture on your behalf with capture-first discipline.

```bash
pip install ./adapters/hermes_agent          # publishes the hermes_agent.plugins entry point
export DOMAIN_FOUNDRY_URL=http://127.0.0.1:8787
# start (or keep) `domain-foundry serve` running
```

hermes-agent discovers the plugin and calls `register(ctx)`; inject
[`adapters/hermes_agent/SKILL.md`](../adapters/hermes_agent/SKILL.md) into the
agent's system prompt. Supported hermes-agent range: **`>=0.4,<0.7`**. See the
[adapter README](../adapters/hermes_agent/README.md) for details.

## Clean-machine gate (automated slice)

```bash
scripts/quickstart_gate.sh
```

Runs steps 2–4 against a throwaway `--home`, activates the food + travel packs,
captures a single-domain and a cross-domain message, and asserts both routed —
the automatable core of the 15-minute gate. The manual slice (browser app +
hermes-agent capture) is steps 5–6 above.
