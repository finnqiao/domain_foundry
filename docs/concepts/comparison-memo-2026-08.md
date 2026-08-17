# Slice 3 comparison memo: what generalized

## Decision

The sourdough golden path is now a declarative proof rather than a reason to
add sourdough behavior to core. The reusable seam is a pack capability plus a
generic projection consumer:

- derived metrics are declared as safe expressions over pack fields;
- galleries are declared over attachment fields and rendered by a generic
  media block;
- comparisons are declared over an object type, label, and metric ids;
- projections, operations, and fixtures stay in the pack;
- imports use a pack-declared mapping with preview, commit, provenance, and
  idempotency.

Sourdough, held-out coffee, and held-out climbing contract tests exercise these
seams. The tests also inspect the generic capability/projection modules to
ensure they contain no domain-name branch.

## What was deliberately not generalized

The current Japanese quiz grader remains the first local implementation behind
the session shell. The shell is generic in its API and declaration shape, but
it does not claim that every future domain already has a quiz engine. Likewise,
schedule status is durable local mesh state, not a live calendar or
notification integration. External providers, LLM responses, real-calendar
events, and human evidence need separate adapters and real receipts.

This boundary keeps the core honest: a capability can describe a contract
without fabricating an implementation or live evidence for every pack.

## Navigation and provenance

Comparison rows retain their pack projection identity and can open the existing
detail route. Detail views continue to carry `?detail=` and receipt/provenance
links. A comparison or gallery is therefore a read projection over captured
evidence, not a second mutable source of truth.

## Follow-up gates

The next validation is evidence collection, not another core branch: a real
month of sourdough use, a real week of Japanese use, and any external provider,
LLM, calendar, notification, or human-quality claim. Until those gates are
opened, deterministic fixtures remain clearly labeled as proof of mechanics.
