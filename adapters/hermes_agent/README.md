# hermes-agent adapter (P8)

A thin hermes-agent **plugin** that maps the harness runtime surface onto a
running `domain-expert serve` over HTTP:

| Tool | HarnessAPI endpoint |
|---|---|
| `domain_expert_capture` | `POST /api/capture` |
| `domain_expert_query` | `GET /api/query` |
| `domain_expert_correct` | `POST /api/correct` |
| `domain_expert_review_list` | `GET /api/review` |
| `domain_expert_review_resolve` | `POST /api/review/{id}/resolve` |
| `domain_expert_new_domain` | `POST /api/wizard` |
| `domain_expert_wizard_reply` | `POST /api/wizard/{id}/reply` |

It ships as `plugin.yaml` + a `register(ctx)` entry point and publishes via the
`hermes_agent.plugins` pip entry-point group. The capture-first behavioral
guidance lives in [`SKILL.md`](./SKILL.md) and is also exported as
`domain_expert_hermes_agent.plugin.CAPTURE_FIRST_GUIDANCE`.

## Supported hermes-agent versions

**`>=0.4,<0.7`** (`SUPPORTED_HERMES_AGENT`). The `register(ctx)` hook is
defensive about the host API: it discovers the host's tool-registration method
(`register_tool` / `add_tool` / `register_tools` / …) and falls back to stashing
the tool list on the context. Bumping the upper bound is a reviewed change gated
by the conformance test (`tests/contract/test_hermes_agent_adapter.py`).

## Install

```bash
# from a checkout
pip install ./adapters/hermes_agent
# or editable for development
pip install -e ./adapters/hermes_agent
```

This registers the `hermes_agent.plugins` entry point `domain_expert`, so
hermes-agent discovers it automatically once installed in the same environment.

## Configure

The plugin reads its target from the host context first, then the environment:

| Setting | Env | Default |
|---|---|---|
| `base_url` | `DOMAIN_EXPERT_URL` | `http://127.0.0.1:8787` |
| `token` | `DOMAIN_EXPERT_API_TOKEN` | _(none; required for non-local binds)_ |

## Usage (standalone)

```python
from domain_expert_hermes_agent import DomainExpertClient, build_tools

client = DomainExpertClient("http://127.0.0.1:8787")
tools = build_tools(client)
capture = next(t for t in tools if t.name == "domain_expert_capture")
print(capture(text="baked a 75% hydration country loaf, came out great"))
```

## Hook up to hermes-agent

1. Start the harness: `domain-expert init && domain-expert serve`.
2. Install this adapter into the hermes-agent environment (see **Install**).
3. hermes-agent discovers the `hermes_agent.plugins` entry point and calls
   `register(ctx)`; inject `SKILL.md` into the agent's system prompt/skill set.
4. Point `DOMAIN_EXPERT_URL` at your `serve` instance if it is not on the
   default localhost port.

See `../../docs/QUICKSTART.md` for the full clean-machine walkthrough.
