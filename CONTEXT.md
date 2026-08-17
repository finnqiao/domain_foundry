# domain_foundry context

## Purpose

`domain_foundry` is a pack-driven workspace for turning domain records into
auditable views, actions, and agent-facing workflows. A domain pack describes a
domain; the core supplies the shared runtime.

## System nouns

- A **pack** is the domain-owned bundle: schema, operations, policy, routing,
  projections, capability declarations, and deterministic fixtures.
- A **record** is the current structured domain state. An **event** is an
  append-only ledger entry. An **action** is a validated operation that may
  change records. A **receipt** records the resulting provenance.
- A **projection** is a pack-declared read model compiled into blocks. Block
  data must remain generic; the pack supplies field names, metrics, media, and
  comparison configuration.
- **Attachments** are content-addressed evidence linked from ledger captures.
  UI detail links preserve the existing `?detail=` navigation and receipt
  context.
- **Sessions** and **schedules** are mesh state. The Slice 3 API provides a
  small, pack-declared shell for them; a shell is not evidence of an external
  provider or a production calendar integration.

## Ownership boundaries

Packs own domain vocabulary and declarations. Core owns validation, routing
infrastructure, capture/apply/provenance, safe capability evaluation, and the
generic projection blocks. Core must not branch on a domain name or learn a
domain-specific metric, gallery, comparison, quiz, or schedule.

The Japanese pack declares import, review-session, and schedule capabilities.
Its deterministic importer and the current local quiz engine are the first
implementation of the shell. Provider/LLM behavior, live calendar behavior,
notifications, and human evidence remain explicit gates. The sourdough pack
proves derived metrics, media/gallery, comparison, and pack-declared
projections using fixtures. Coffee and climbing are held-out synthetic proof,
not claims about live data.

## Compatibility contract

`capabilities.yaml` is optional pack metadata. It declares a core compatibility
specifier and versioned capability payloads. The loader rejects unknown
capabilities, unsupported versions, and incompatible core ranges before the
pack is usable. Capability expressions are evaluated by a restricted generic
expression evaluator; arbitrary Python is not a pack extension mechanism.

The compatibility and capability details live in
[`docs/concepts/capabilities.md`](docs/concepts/capabilities.md). The decision
to keep these seams pack-owned is recorded in
[`docs/adr/007-declarative-capabilities.md`](docs/adr/007-declarative-capabilities.md).
The Slice 3 extraction rationale is in
[`docs/concepts/comparison-memo-2026-08.md`](docs/concepts/comparison-memo-2026-08.md).

## Evidence gates

Fixtures are deterministic and local. They prove shape, validation, routing,
projection, and provenance only. The following remain intentionally unclaimed
until a human supplies evidence:

- a real month of sourdough use;
- a real week of Japanese use;
- external providers and LLM-backed behavior;
- a live calendar, notification delivery, or scheduling integration;
- human-quality evidence and review.

When a gate is opened, record the source and receipt rather than replacing a
fixture with an implied live claim.
