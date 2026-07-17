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

Let an agent capture on your behalf with capture-first discipline. Prefer an
**isolated Hermes profile** so this never touches your default gateway:

```bash
# 1) isolated profile (clone keys/config; sticky default stays put)
hermes profile create domainfoundry --clone

# 2) install adapter into the *hermes* Python (Hermes venvs often have no pip)
HERMES_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
uv pip install --python "$HERMES_PY" -e ./adapters/hermes_agent

# 3) enable plugin + toolset on that profile only (pip plugins are not listed
#    by `hermes plugins enable` on Hermes 0.14 — edit config.yaml):
#    plugins.enabled: [domain_foundry]
#    platform_toolsets.cli: [..., domain_foundry]

export DOMAIN_FOUNDRY_URL=http://127.0.0.1:8787
domain-foundry serve   # terminal 1
hermes -p domainfoundry -z "baked a 75% hydration country loaf" --yolo
```

Or run the automated smoke: `scripts/hermes_e2e_smoke.sh`.

Supported hermes-agent range: **`>=0.4,<1`**. See the
[adapter README](../adapters/hermes_agent/README.md) for details.

## Clean-machine gate (automated slice)

```bash
scripts/quickstart_gate.sh
```

Runs steps 2–4 against a throwaway `--home`, activates the food + travel packs,
captures a single-domain and a cross-domain message, and asserts both routed —
the automatable core of the 15-minute gate. The manual slice (browser app +
hermes-agent capture) is steps 5–6 above.
