# Security Policy

## Supported versions

Security fixes are accepted against the latest released `0.x` line until `1.0`.

## Reporting a vulnerability

Email security reports privately (do not open a public issue for exploit details).
Include: affected version, reproduction steps, impact assessment, and any suggested fix.

We aim to acknowledge within 72 hours and ship a fix or mitigation for confirmed
issues as quickly as practical.

## Design posture

- Canonical data lives in local SQLite; the API binds to `127.0.0.1` by default.
- Non-local binding requires an explicit flag **and** a bearer token.
- All writes are parameterized; table/column names are validated against the
  compiled schema registry.
- Query paths use read-only SQLite connections.
- Path writes go through `safe_join` (workspace-rooted only).
- Secrets are redacted before persistence into notes, receipts, or logs.
- Foundry rejects credential-shaped brief content before it reaches a configured
  reasoning model or research provider and bounds all prompt-bearing fields.
- Model and search output is untrusted, schema validated, and closed against
  supplied evidence and contract identifiers before compilation.
- Generated applications ship with a network-denying Content Security Policy;
  preview iframes are sandboxed, and record content is escaped before rendering.
- Foundry bundles are staged before an atomic rename and include a frozen
  evidence snapshot plus hashes for every owned artifact.
- Third-party Domain Packs are data (YAML/SQL/JSONL), not executable code in v1.
- There is no telemetry.

The Foundry-specific boundaries, attacks, controls, and residual risks are in
[`docs/concepts/foundry-threat-model.md`](docs/concepts/foundry-threat-model.md).
