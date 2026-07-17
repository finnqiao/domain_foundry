# Nous community post draft (not posted)

> Draft only. Finn posts by hand at launch. Nous is an agent-runtime community,
> so lead with the adapter/runtime story, not the app. Avoid any "Hermes"
> name collision in the product name.

## Title

`Domain Foundry: a structured-life data layer your agent can capture into`

## Body

If you run an agent that receives messages (Telegram/WhatsApp/CLI), you've
probably hit the wall where the agent is great at *talking* but has nowhere good
to *put* the structured facts a user drops in passing — "watered the monstera",
"that bake was 80% hydration", "dinner at River Station then Port City in March".

Domain Foundry is a local-first harness that solves the storage/structuring half:

- Your agent calls one tool — **capture** — with the raw text. The harness stores
  it capture-first (raw + provenance before interpretation), routes it into the
  right domain object, and never drops it (applied / review / unfiled /
  ledger-only).
- Users define domains as **data-only packs** (six YAML files). No per-domain
  code, no schema migrations to hand-write.
- Corrections are one message and become replayable eval cases, so routing
  quality is enforceable, not vibes.

### The adapter

It ships a **hermes-agent plugin**: `register(ctx)` + `plugin.yaml`, published on
the `hermes_agent.plugins` entry-point group, exposing capture / query / correct
/ review / new_domain over the harness's local HTTP API. There's a capture-first
`SKILL.md` guidance fragment to drop into the agent's system prompt, and a
conformance test that runs a scripted capture → correct → review session against
a live local stack. Supported range is pinned (`>=0.4,<0.7`) and gated by that
test.

The core is runtime-agnostic (stable HTTP contract), so an MCP adapter is the
same shape — anyone can write one against the documented endpoints.

MIT, local-first, no telemetry. Repo + adapter guide: <link>. Would love feedback
from folks building capture pipelines into their runtimes.
