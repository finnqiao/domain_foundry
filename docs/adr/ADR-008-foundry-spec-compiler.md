# ADR-008: One evidence-backed FoundrySpec compiles preview and owned app

- Status: accepted
- Date: 2026-08-19

## Context

The prior creation flow could suggest a domain shell from conversation, but a
generic shell plus a role prompt did not preserve research quality, schema
reasoning, product alternatives, visual intent, or proof. Preview and runtime
could also drift when different paths interpreted the same idea.

## Decision

Every evidence-backed application is represented by a strict, versioned
`FoundrySpec`. The staged pipeline separately produces research, three
structurally different product concepts, the selected remix, a workload-derived
domain model, an experience contract, implementation boundaries, and
derivations. Source, evidence, principle, concept, entity, relationship,
workload, view, action, and evaluation identifiers are closed before build.

The deterministic compiler is the only producer of the preview and the owned
application bundle. It emits executable SQLite DDL, a self-contained offline
HTML application, the exact JSON spec, a frozen evidence snapshot, a README,
and a content-hashed build receipt. The HTML shown in Foundry Studio is the same
artifact written to disk.

The model cannot author the only release cases. At least two tasks come from the
user and the compiler adds fixed schema, workload, accessibility, and security
cases. An interest without reviewed vertical evidence or an enabled research
adapter fails closed.

## Consequences

Product, data, experience, implementation, export, and evaluation decisions are
inspectable and reproducible. Golden verticals can share safe primitives while
remaining structurally and visually distinct. Remix operations keep parentage
and evidence instead of becoming an untraceable prompt edit.

The contract is intentionally demanding: provider output that cannot satisfy
it fails instead of silently degrading. Live-provider quality, external-user
value, manual assistive-technology testing, and external security review remain
release evidence outside the compiler itself.

ADR-009 closes a subsequent runtime gap: the owned application must interpret
typed region and action semantics, preserve correction versions, and validate
backup restore rather than flattening a rich spec into a generic record list.
