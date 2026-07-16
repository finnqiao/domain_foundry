# ADR-002: Two-database layout

**Status:** Accepted  
**Date:** 2026-07-16

## Context

The capture substrate (events, interpretations, approvals, journal) evolves
independently from pack-owned domain tables. A single DB couples migration
cadence and complicates pack install/uninstall.

## Decision

Use two SQLite databases under `~/.domain_expert/`:

- `ledger.sqlite` — substrate tables (capture, entry, interpretation, journal, …)
- `domains.sqlite` — pack-owned tables named `<pack>__<object>`

Cross-DB references are soft (`entry_id` / `object_uid` strings).

## Consequences

- Pack migrations cannot break the substrate.
- Postgres export later is a schema translation, not a redesign.
- Integrity checks run per store.
