# ADR-001: HTTP adapter contract

**Status:** Accepted  
**Date:** 2026-07-16

## Context

Runtime adapters (hermes-agent, future OpenClaw/MCP) need a stable way to call
the harness. In-process imports couple adapter and core to the same venv and
Python version.

## Decision

Adapters talk to core over HTTP (`http://127.0.0.1:<port>`) against the
`HarnessAPI` surface. The CLI and SPA use the same API.

## Consequences

- Survives venv/runtime mismatches.
- Every adapter is a thin HTTP client (~same tool surface).
- Requires `domain-expert serve` as the local daemon.
