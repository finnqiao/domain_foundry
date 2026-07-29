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

Either let `setup` walk you through it (it runs `init` for you):

```bash
domain-foundry setup
```

…or do it yourself, if you'd rather configure models by hand:

```bash
domain-foundry init
```

Creates `~/.domain_foundry/` with the two SQLite databases (`ledger.sqlite`,
`domains.sqlite`) and applies substrate migrations.

### Bring your own key

Nothing ships with a model. `setup` asks which provider you have a key for
(Anthropic, OpenAI, DeepSeek, OpenRouter, anything OpenAI-compatible you host
yourself, or none at all), suggests a model for each of the two tiers, and makes
one cheap live call per tier to prove the key works:

```
Checking each tier can reach its model:
  routine  claude-haiku-4-5             ok — reachable
  sota     claude-opus-5                ok — reachable
```

That probe matters: without it, a wrong key or a renamed model shows up as
*silence*. Captures keep succeeding, because routing falls back to keyword rules
— so the failure looks exactly like "I haven't set a key yet".

**The two tiers, and why there are two:**

| Tier | Handles | Shape of the call |
|---|---|---|
| `routine` | every capture's routing + field extraction | high volume, low stakes |
| `sota` | corrections, structural/schema-affecting ops, low-confidence and multi-domain fan-out | rare, high stakes |

Escalation is automatic (`select_model_tier`): a routing rule can declare
`tier: sota`, and anything that updates/deletes/merges, reads as a correction,
comes back below 0.7 confidence, or matches multiple packs escalates on its own.

**Settings resolve in three layers, most specific first** — environment
variables, then the config file `setup` wrote (`~/.domain_foundry/config.toml`),
then the provider's suggestion. So an expert setup that lives in a dotfile keeps
working untouched:

```bash
export DOMAIN_FOUNDRY_SOTA_MODEL=claude-opus-5
export DOMAIN_FOUNDRY_SOTA_API_KEY=...
domain-foundry setup --show      # what resolved, and from where (keys redacted)
```

By default the config file records *which env var holds your key*, not the key
itself. `--store-key` opts into writing it, and then the file is `chmod 0600`.

Non-interactive, for scripts and clean-machine installs:

```bash
domain-foundry setup --provider anthropic --sota claude-opus-5 -y --no-probe
```

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

## 7. (Optional) Private pack overlay

Personal packs do not belong in this checkout. Point Domain Foundry at a private
catalog (see [Private overlay](PRIVATE_OVERLAY.md)):

```bash
export DOMAIN_FOUNDRY_PACKS_PATH=~/HermesWorkspace/packs
domain-foundry pack list   # includes overlay packs; same-named overlay wins
```

## Clean-machine gate (automated slice)

```bash
scripts/quickstart_gate.sh
```

Runs steps 2–4 against a throwaway `--home`, activates the food + travel packs,
captures a single-domain and a cross-domain message, and asserts both routed —
the automatable core of the 15-minute gate. The manual slice (browser app +
hermes-agent capture) is steps 5–6 above.
