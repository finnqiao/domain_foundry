# ADR-003: ULID identity

**Status:** Accepted  
**Date:** 2026-07-16

## Context

Stable, sortable identifiers are required for captures, entries, approvals, and
canonical objects. UUIDv4 is opaque and non-sortable; timestamped custom IDs
invite collisions and clock skew bugs.

## Decision

All public IDs are ULIDs (Crockford base32). Canonical object UIDs use the form
`<pack>:<object_type>:<ulid>`. Timestamps are UTC ISO-8601.

## Consequences

- Lexicographic sort ≈ chronological order.
- Postgres export stays a translation.
- Clock injection in tests/evals remains mandatory.
