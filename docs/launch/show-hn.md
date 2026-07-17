# Show HN draft (not posted)

> Draft only. Finn posts this by hand at launch (see `LAUNCH_CHECKLIST.md`).
> Swap the final product name and the repo URL before posting.

## Title

`Show HN: Domain Foundry – describe a passion, get a local-first app you talk to`

(Alt: `Show HN: A local-first harness that turns messages into structured domain data`)

## URL

`https://github.com/domain-foundry/domain_foundry`

## Text

I got tired of my hobbies living as unstructured notes and half-abandoned
spreadsheets. Domain Foundry is a local-first personal agent harness: you
describe a domain you care about (sourdough, houseplants, dive logs, whatever),
you get a small "pack" that gives you a schema + a routed capture pipeline + a
little app — and then you just talk to it in plain language.

The design is built around two hard rules:

- **Capture-first**: the raw message + provenance hit an append-only ledger
  *before* any interpretation. If the interpreter or the machine falls over, your
  words are still there.
- **Never-drop**: every capture ends up applied, queued for review, parked as an
  unfiled card, or kept ledger-only. Nothing is silently discarded — and the eval
  corpus holds "false-completed-actions" (acting on something it shouldn't) at
  zero, as a release-blocking gate.

Some things that might be interesting to this crowd:

- **Routing is two-layer and cost-aware.** Zero-token regex rules handle the
  common case; an LLM interpreter is only invoked when a capture is ambiguous,
  structured, or spans multiple domains — and its output is constrained to the
  pack's schema, so captured text can never trigger tool execution.
- **Packs are data, not code.** A domain is six YAML files (schema, routing,
  policy, operations, projections, manifest). `pack validate` checks a pack fully
  offline. Sharing a pack can't execute code.
- **Corrections are the training loop.** You fix the record in one message
  ("that bake was 80% hydration not 75"); it revises the canonical row, preserves
  history, and backfills a replayable eval case. Real mistakes become regression
  tests.
- **Local-first, no telemetry.** Canonical data is SQLite on your machine. The
  API binds to localhost; a non-local bind refuses to start without a token.
- **Runtime-agnostic.** The core is a stable HTTP surface; the CLI, the React
  app shell, and a hermes-agent plugin are all thin clients of it.

It's MIT, Python 3.11+, `pipx install` and go. There are four synthetic reference
packs (food, travel, plants, sourdough) and a "remix in an afternoon" tutorial
that builds a plant-care pack from scratch.

Docs: <link>. Quickstart is ~5 minutes; a clean-machine gate script is in the
repo.

Honest caveats: it's pre-1.0, single-user/local only (multiplayer/Postgres is a
designed-for-later, not-built-yet thing), routing quality on a brand-new domain
depends on the examples you give the pack, and the final product name isn't
locked yet. Feedback on the pack format and the routing model especially welcome.

## First-comment seed (post as a reply to your own thread)

Architecture + the "why capture-first / never-drop" reasoning is here: <docs
architecture link>. Happy to go deep on the routing tiers, the correction →
eval-case loop, or the packs-are-data trust model.
