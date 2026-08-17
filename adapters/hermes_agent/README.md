# hermes-agent adapter (P8)

A hermes-agent **plugin** that maps the harness runtime surface onto the
canonical `domain-foundry serve` HTTP contract, with a conformance-tested
in-process embedding available when the host does not need a network hop:

| Tool / client method | HarnessAPI endpoint |
|---|---|
| `domain_foundry_capture` | `POST /api/capture` |
| `domain_foundry_query` | `GET /api/query` |
| `domain_foundry_ask` | `POST /api/ask` |
| `domain_foundry_correct` | `POST /api/correct` |
| `domain_foundry_review_list` | `GET /api/review` |
| `domain_foundry_review_resolve` | `POST /api/review/{id}/resolve` |
| `domain_foundry_new_domain` | `POST /api/wizard` (atlas neighborhood, not an install) |
| `domain_foundry_wizard_reply` | `POST /api/wizard/{id}/reply` |
| `domain_foundry_atlas_search` | `POST /api/atlas/search` |
| `domain_foundry_inspect_pack` | `GET /api/packs/{name}/inspect` |
| `domain_foundry_suggest` | `GET /api/wizard/{domain}/suggest` |
| `domain_foundry_apply_pack_edit` | `POST /api/packs/{name}/edit` |
| `DomainExpertClient.activate_pack` | `POST /api/packs/activate` |
| `DomainExpertClient.export` | `GET /api/export` |

It ships as `plugin.yaml` + a `register(ctx)` entry point and publishes via the
`hermes_agent.plugins` pip entry-point group. The capture-first behavioral
guidance lives in [`SKILL.md`](./SKILL.md) and is also exported as
`domain_foundry_hermes_agent.plugin.CAPTURE_FIRST_GUIDANCE`.

## Supported hermes-agent versions

**`>=0.4,<1`** (`SUPPORTED_HERMES_AGENT`). The `register(ctx)` hook speaks
Hermes 0.14+'s `register_tool(name, toolset, schema, handler)` API and stays
backward-compatible with older fakes that used `parameters=`. Conformance tests
gate the actually-exercised host surface.

## Install

```bash
# Install into the *hermes* Python (Hermes venvs often ship without pip).
HERMES_PY="${HERMES_PY:-$HOME/.hermes/hermes-agent/venv/bin/python}"
uv pip install --python "$HERMES_PY" -U -e ./adapters/hermes_agent

# Prefer an isolated profile so default gateway config stays untouched:
#   hermes profile create domainfoundry --clone
# Then enable plugin + toolset on that profile (see below), or just run:
#   scripts/hermes_e2e_smoke.sh
#   HERMES_LIVE=1 scripts/hermes_e2e_smoke.sh   # optional LLM oneshot
```

This registers the `hermes_agent.plugins` entry point `domain_foundry`. On
Hermes 0.14+, `hermes plugins enable` does **not** list pip entry-points, so
enable by editing the profile's `config.yaml`:

```yaml
plugins:
  enabled: [domain_foundry]
platform_toolsets:
  cli: [..., domain_foundry]   # required or the model never sees the tools
```

Prefer an isolated Hermes profile (`hermes profile create … --clone`) so this
does not touch your default gateway config.

## Configure

The plugin reads its target from the host context first, then the environment:

| Setting | Env | Default |
|---|---|---|
| `base_url` | `DOMAIN_FOUNDRY_URL` | `http://127.0.0.1:8787` |
| `token` | `DOMAIN_FOUNDRY_API_TOKEN` | _(none; required for non-local binds)_ |

## Usage (standalone)

```python
from domain_foundry_hermes_agent import DomainExpertClient, build_tools

client = DomainExpertClient("http://127.0.0.1:8787")
tools = build_tools(client)
capture = next(t for t in tools if t.name == "domain_foundry_capture")
print(capture(text="baked a 75% hydration country loaf, came out great"))
```

## Hook up to hermes-agent

1. Start the harness: `domain-foundry init && domain-foundry serve`.
2. Install this adapter into the hermes-agent environment (see **Install**).
3. hermes-agent discovers the `hermes_agent.plugins` entry point and calls
   `register(ctx)`; inject `SKILL.md` into the agent's system prompt/skill set.
4. Point `DOMAIN_FOUNDRY_URL` at your `serve` instance if it is not on the
   default localhost port.

See `../../docs/QUICKSTART.md` for the full clean-machine walkthrough.
