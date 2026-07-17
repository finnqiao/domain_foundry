# ADR-004: Packs are data

**Status:** Accepted  
**Date:** 2026-07-16

## Context

Domain extensibility must be safe for non-expert users. Arbitrary Python from
third-party packs is a supply-chain risk.

## Decision

In v1, Domain Packs are declarative data: YAML manifests, generated SQL
migrations, JSONL eval fixtures. The ApplyEngine executes a closed operation
vocabulary against compiled schemas.

Python handlers are allowed only via separately-installed pip packages that
register through the `domain_foundry.packs` entry-point group — an explicit
trust decision by the user.

## Consequences

- `pack validate` can fully check a pack offline.
- Remix culture can share packs like Obsidian plugins.
- Exotic domains may need a trusted pip handler later.
