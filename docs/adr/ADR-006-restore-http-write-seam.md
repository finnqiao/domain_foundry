# ADR-006: Restore the HTTP write seam

**Status:** Accepted
**Date:** 2026-08-10
**Re-affirms:** [ADR-001](ADR-001-http-adapter-contract.md)

## Context

ADR-001 (accepted 2026-07-16) decided that adapters, the CLI, and the SPA talk
to the harness over one HTTP contract served by `domain-foundry serve`.

The mesh P0 work later removed every mutating HTTP endpoint — `POST
/api/capture`, `/api/correct`, `/api/packs/activate`,
`/api/review/{id}/resolve`, `/api/review/bulk-resolve`,
`/api/projections/drain`, `/api/wizard`, `/api/wizard/{id}/reply` returned
`410 Gone` — and moved writes in-process (embedded `HarnessAPI` in the CLI,
MCP, Telegram, and hermes-agent adapters). The SPA kept all of its mutation
controls: the capture box, Install buttons, correction dialog, review
approve/deny, and bulk triage all POSTed to endpoints that could only fail.
Contract tests asserted the 410s, so the suite stayed green over a broken
product. ADR-001 was contradicted by the implementation but never superseded.

The 2026-08-08 vision/gap review (`docs/VISION_GAP_REVIEW_2026-08-08.md`,
the critical web contract failure section) named this the first release
blocker.

## Decision

1. **The local FastAPI daemon (`domain-foundry serve`) is the canonical
   mutation seam** for the SPA, MCP, Telegram, Roamboard, and any other
   ingress that does not embed the harness. Request bodies are validated
   Pydantic models (`core/domain_foundry_core/api/schemas.py`); receipts are
   the same shapes `HarnessAPI` returns in-process.
2. **Auth posture:** open on localhost when no token is configured; when
   `DOMAIN_FOUNDRY_API_TOKEN` (or `--token`) is set, every endpoint — read and
   write — requires the bearer token; non-local binds refuse to start without
   a token (`api/app.py::run_server`).
3. **In-process embedding remains legal, but only with conformance.** An
   adapter may embed `HarnessAPI` directly (as the MCP, Telegram, and
   hermes-agent adapters do today) *only if* it passes the Gate-1 conformance
   suite — the same create → activate → capture → query → correct → review
   journey every ingress must pass, defined in
   `docs/build-plan-2026-08/02-SLICE-1-ACTIVATION.md`. Embedding without
   conformance is not a supported integration.
4. **The mesh journal/fast-path stays experimental and default-off.** The
   Concierge/Expert/Supervisor path is not the canonical write seam. Its
   behavior flags live in `core/domain_foundry_core/mesh/flags.py`; expert
   process lifecycle (launchd install) is stubbed, and mesh CLI/API output
   says so explicitly.

## Consequences

- **Two WAL writers are supported and tested.** The daemon process and an
  embedded-harness process (e.g. the MCP server) may both write the SQLite
  stores; WAL mode plus the existing concurrency tests cover this. New
  embedded writers must run the Gate-1 suite.
- **`domain-foundry serve` is required for the SPA.** A dead daemon blocks
  browser capture (it never blocks CLI/MCP capture, which embed the harness).
  The trade against mesh P0's "a dead server can no longer block capture" is
  accepted: an advertised control that cannot work is worse than a daemon
  dependency that is visible and testable.
- The Playwright journey (`app/e2e/activation.spec.ts`) and the HTTP contract
  tests (`tests/contract/`) are the executable form of this decision; a future
  change to the write seam must flip those tests first, and must supersede
  this ADR rather than silently diverge.
- ADR-001's status gains a re-affirmation pointer to this record.
