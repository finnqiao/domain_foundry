# ADR-007: Declarative pack capabilities and compatibility

- Status: accepted
- Date: 2026-08-10

## Context

The sourdough golden path needed derived metrics, media, and comparison while
Japanese needed import, session, and schedule shells. Encoding those examples
as domain checks in core would make the next pack more expensive and would make
the architecture difficult for an agent to navigate.

## Decision

Packs may declare versioned capabilities in `capabilities.yaml`. The core
loader validates the capability name, capability version, and core/capability
specifier ranges. Generic projection and import consumers read the declaration
data. Derived values use a restricted expression evaluator; arbitrary code is
not loaded from a pack.

Each capability needs deterministic pack fixtures and a contract test. A
held-out domain test must exercise the generic seam without adding a domain
branch to core. Unsupported capability versions fail closed at pack load time.

## Consequences

Capability declarations make pack ownership and compatibility visible. They
also make missing implementations explicit: the Japanese quiz shell currently
uses the local engine, while provider/LLM and live-calendar behavior remain
gates. Fixtures prove deterministic mechanics, routing, projection, and
provenance only.

The existing detail navigation and receipts remain core contracts. A capability
does not create a new source of truth; it describes how a generic consumer
projects captured records and attachments.
