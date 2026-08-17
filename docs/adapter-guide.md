# Adapter guide

An **adapter** lets a runtime (an agent framework, a chat bot, an MCP host) drive
the harness. The canonical integration seam is the **HTTP contract** served by
`domain-foundry serve` ([ADR-001](adr/ADR-001-http-adapter-contract.md),
re-affirmed by ADR-006). An adapter may embed `HarnessAPI` in-process only while
it passes the Gate-1 conformance suite; otherwise it should remain a thin HTTP
client so it survives venv/runtime/Python-version mismatches.

The first shipped adapter is the **hermes-agent plugin**
(`adapters/hermes_agent/`).

## The contract

Point your adapter at a running `domain-foundry serve` (default
`http://127.0.0.1:8787`) and expose these operations as tools:

| Tool | HTTP endpoint |
|---|---|
| capture | `POST /api/capture` |
| query | `GET /api/query` |
| correct | `POST /api/correct` |
| review list | `GET /api/review` |
| review resolve | `POST /api/review/{id}/resolve` |
| new domain | `POST /api/wizard` |
| wizard reply | `POST /api/wizard/{id}/reply` |

That is the whole surface an adapter needs. There is **no privileged write
path** — everything mutates through `capture` / `correct` / review, exactly like
the CLI and app shell.

## Configuration

| Setting | Env | Default |
|---|---|---|
| base URL | `DOMAIN_FOUNDRY_URL` | `http://127.0.0.1:8787` |
| bearer token | `DOMAIN_FOUNDRY_API_TOKEN` | none (required for non-local binds) |

When the daemon binds anywhere other than localhost it refuses to start without
a token, and all requests must carry `Authorization: Bearer <token>`. Localhost
binds are open by default for zero-friction local use.

## The hermes-agent plugin

Install it into the same environment as hermes-agent:

```bash
pip install ./adapters/hermes_agent      # or: pip install -e ./adapters/hermes_agent
```

This publishes a `register(ctx)` entry point on the **`hermes_agent.plugins`**
group, so hermes-agent discovers and wires it automatically. The plugin:

- declares itself via `plugin.yaml`,
- registers seven tools (`capture` / `query` / `correct` / `review_list` /
  `review_resolve` / `new_domain` / `wizard_reply`),
- is defensive about the host API: it discovers the host's tool-registration
  method (`register_tool` / `add_tool` / `register_tools` / …) and otherwise
  stashes the tool list on the context.

### Capture-first behavioral guidance

Inject `adapters/hermes_agent/SKILL.md` into the agent's system prompt (also
exported as `CAPTURE_FIRST_GUIDANCE`). It teaches the agent to **capture the raw
message first** and let the harness interpret — rather than pre-structuring or
dropping ambiguous input.

### Supported version range

**`>=0.4,<1`** (`SUPPORTED_HERMES_AGENT`). Upper bound stays loose so
`hermes update` does not block discovery; the conformance test
(`tests/contract/test_hermes_agent_adapter.py`) gates the actually-exercised
host surface (capture → query → correct → review against a live in-process
stack). Hermes 0.14+ uses `register_tool(name, toolset, schema, handler)` and
expects the pip entry point to load a **module** (not `module:register`).

## Standalone use

The client + tools are usable without hermes-agent:

```python
from domain_foundry_hermes_agent import DomainExpertClient, build_tools

client = DomainExpertClient("http://127.0.0.1:8787")
tools = build_tools(client)
capture = next(t for t in tools if t.name == "domain_foundry_capture")
print(capture(text="baked a 75% hydration country loaf, came out great"))
```

## Writing a new adapter

1. Wrap the endpoints above as tools in your runtime's tool format.
2. Read config from the host context first, then the environment.
3. Send the bearer token when present.
4. Ship a capture-first guidance fragment for the agent.
5. Add a conformance test that runs capture → correct → review against a live
   local stack, and pin the host version range.

MCP is a supported adapter and follows the same harness contract; its current
implementation embeds `HarnessAPI` in-process and its HTTP driver is covered by
the Gate-1 seed journey.

## Roamboard sync adapter (Phase 7)

`adapters/roamboard/` imports Roamboard feed / patch shapes into the **travel**
pack via in-process `HarnessAPI` (no HTTP hop). CLI:

```bash
domain-foundry roamboard sync --dry-run --feed path/to/feed.json   # default
domain-foundry roamboard sync --apply --feed path/to/feed.json
domain-foundry roamboard sync --shadow --feed path/to/feed.json \
  --travel-db ~/HermesWorkspace/travel/data/travel.sqlite
```

Shadow reports land under `{DF_HOME}/shadow/roamboard/`. Private
`travel.sqlite` is read-only; launchd cutover remains manual. See
[`adapters/roamboard/README.md`](../adapters/roamboard/README.md).
