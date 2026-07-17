# lobste.rs draft (not posted)

> Draft only. Finn submits by hand at launch. lobste.rs is invite-gated and
> allergic to marketing — keep it technical and short.

## Submission

- **URL:** `https://github.com/domain-foundry/domain_foundry`
- **Title:** `Domain Foundry: a local-first, capture-first harness for structured personal data`
- **Tags:** `ai`, `databases`, `python` (mark as **show**)

## Author comment (required for "show")

I built a local-first personal agent harness. The interesting parts for this
crowd are the invariants and the extension model, not the LLM angle:

- **Append-only capture ledger** in SQLite: raw message + provenance are written
  before interpretation; interpretation is a separate row that references it.
  Two databases (substrate vs pack-owned) with soft cross-DB refs so pack
  migrations can't corrupt the substrate, and a Postgres export stays a
  translation (ULIDs + UTC everywhere).
- **Two-layer routing:** deterministic regex rules first (zero tokens), an LLM
  interpreter only on ambiguity/multi-domain, output constrained to the pack
  schema. Cassette-replayed in CI so the routing gate is deterministic and
  token-free.
- **Packs are data, not code:** a domain is six YAML files; `pack validate` is
  offline and total; installing a pack can't execute code. There's an explicit
  trusted-code escape hatch (pip entry-point handlers, side-loaded React blocks)
  that's labeled as such.
- **Corrections → eval cases:** a one-message NL correction revises the canonical
  row (revision chain preserved) and backfills a replayable regression case.
- **Frozen-clock discipline:** a lint/audit bans wall-clock calls outside one
  injectable provider, which keeps evals deterministic.

MIT, Python 3.11+. Feedback on the pack format and the routing tiers welcome.
Pre-1.0 and single-user/local only right now.
