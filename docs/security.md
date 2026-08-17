# Security posture

`domain_foundry` is local-first, has **no telemetry**, and treats your captured
text as untrusted input to a structured interpreter — never as executable
instructions. This page documents the posture; the disclosure process is in the
repository [`SECURITY.md`](https://github.com/finnqiao/domain_foundry/blob/main/SECURITY.md).

## Threat model in one paragraph

Canonical data lives in local SQLite on your machine. The only network listener
is the `domain-foundry serve` daemon, which binds `127.0.0.1` by default. The
attack surface is (a) the local HTTP API, (b) prompt-injection via captured
text, (c) path writes into the markdown vault, and (d) third-party extensions
(pip handlers / custom blocks) you explicitly install.

## Network & authentication

- **Localhost by default.** `serve` binds `127.0.0.1:8787`. On a single-user
  machine this needs no auth for zero friction.
- **Non-local bind requires a token.** Binding to anything other than
  `127.0.0.1` / `localhost` / `::1` **refuses to start** without
  `DOMAIN_FOUNDRY_API_TOKEN` (or `--token`).
- **Bearer-gated when a token is set.** Every API endpoint (including
  `/health`) requires `Authorization: Bearer <token>`; missing → `401`, wrong
  → `403`. The served HTML shells bootstrap the token so their API calls use
  the same posture.
- **CORS is pinned** to the local app origins only.

Verified by `tests/contract/test_api.py::test_non_local_bind_requires_token` and
`tests/security/test_api_auth.py` (token gates endpoints; localhost default open).

## No privileged canonical-data write path

The app shell, the CLI, and every adapter mutate canonical records **only**
through `capture()` / `correct()` / review-resolve. Pack lifecycle management is
a separate, explicit administrative surface: it previews declared permissions,
restricts mutations to workspace-owned pack directories, and snapshots before
upgrade/uninstall. There is no back door to write canonical rows. Block/query
paths are **read-only**.

## SQL safety

- All writes are **parameterized**; table and column names are validated against
  the compiled `schema_registry`, so a pack cannot inject arbitrary identifiers.
- Query paths use **read-only** SQLite connections; an allowlist
  (`is_readonly_sql`) rejects anything but `SELECT` / `WITH … SELECT` and blocks
  stacked statements (`SELECT 1; DROP TABLE …`) and `ATTACH`.

Verified by `tests/security/test_path_and_sql.py::test_readonly_sql_allowlist`.

## Path safety

Vault and attachment writes go through `safe_join`, which rejects absolute
paths, `..` traversal, and any target that escapes the workspace root.

Verified by `tests/security/test_path_and_sql.py::test_safe_join_rejects_traversal`.

## Secret redaction

Common secret shapes (API keys, tokens, `key=value` secrets) are redacted before
anything is persisted into notes, receipts, or logs.

Verified by `tests/security/test_path_and_sql.py::test_redact_secrets_common_patterns`.

## Prompt-injection containment

Captured text can never directly trigger tool execution. It is mitigated by:

- interpreter output **constrained to the structured schema** (it can only
  propose declared objects/fields),
- **policy gates** on destructive operations (delete/merge default to review),
- **`confirm`** disposition for sensitive domains,
- the never-drop ladder: worst case, a capture is parked as an unfiled card or
  ledger-only, never silently acted upon (the eval corpus holds
  false-completed-actions at **zero**, release-blocking).

## Extension trust tiers

| Tier | What it is | Can it run code? |
|---|---|---|
| Domain pack | YAML/SQL/JSONL data | **No.** `pack validate` checks it offline. |
| Pip handler | Python via `domain_foundry.packs` entry point | Yes — you chose to `pip install` it. |
| Custom block | React component you drop in | Yes — runs in your browser session. |

Only load pip handlers and custom blocks you wrote or audited.

The Slice 4 automated review record is in
[`docs/SECURITY_REVIEW_2026-08.md`](SECURITY_REVIEW_2026-08.md). It records the
remaining independent-review and external-user gates explicitly.

## Release-blocking leak audit

Every release runs the full leak audit — no tracked `*.sqlite`/binaries, no
private remotes, synthetic-only fixtures, git history starting at P0. See the
[Leak audit](LEAK_AUDIT.md) page and `scripts/release_audit.sh`.

## Reporting a vulnerability

Please report privately (do not open a public issue with exploit detail). See
[`SECURITY.md`](https://github.com/finnqiao/domain_foundry/blob/main/SECURITY.md)
for the process and response targets.
