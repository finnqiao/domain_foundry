# Risks, scope boundaries, human gates, verification matrix

Companion to the slice documents. Read before starting any slice; consult when a
PR seems to want something the plan doesn't cover — it is probably in the
not-in-scope list on purpose.

---

## Risk register

| # | Risk | Mitigation | Where handled |
|---|---|---|---|
| R1 | **Restored HTTP writes vs mesh journal ordering.** The mesh concierge journals channel messages before the ledger; naive HTTP writes could create a second, conflicting ingress discipline. | HTTP handlers call only `HarnessAPI` methods — byte-identical behavior to the CLI path. Mesh fast-path flags stay default-off. ADR-006 records mesh ingress as a separate experimental path, not the canonical seam. | S0.1, S0.3 |
| R2 | **Two writer processes on one SQLite** (serve daemon + embedded MCP/CLI). | WAL mode + existing crash/concurrency tests; `capture` reloads packs per write so the daemon can't hold a stale registry; the Gate-1 suite adds a mixed-ingress restart test. | S0.2, S1.8 |
| R3 | **Adapters embedding `HarnessAPI` drift silently** after the seam decision. | Embedding stays legal per ADR-006 **only with** Gate-1 conformance; hermes already auto-selects HTTP when `DOMAIN_FOUNDRY_URL` is set. | S1.8 |
| R4 | **Localhost auth/token UX.** Too strict = broken first run; too loose = exposed writes. | Keep the tested posture: localhost-open by default, token enforced on every endpoint when configured, non-local bind refuses without a token; tight CORS allowlist; DNS-rebinding/Host-header review scheduled in Gate 4. | S0.1, M4.3 |
| R5 | **LLM cost runaway** (Ask + wizard design). | Every call gated by `CostGuard.allow_llm` and recorded; wizard model-confirm shows estimated cost before running; Ask defaults to the routine tier with bounded output; cap-hit copy is plain language, not an error dump. | S1.4, S1.5 |
| R6 | **Ask injection / unsafe queries.** | Model output is a pydantic-validated `AskPlan` over a registry whitelist; execution only through existing parameterized query modules (the model never writes SQL); citations required; record text wrapped as data-not-instructions; adversarial cases in the ask eval set. | S1.4 |
| R7 | **LLM-designed packs invalid or hallucinated.** | `BlueprintModel` validation → `load_pack(validate=True)` → held-out acceptance before any "live" label; deterministic fallback always available and labeled scaffold. | S1.5 |
| R8 | **Review-decision vocabulary mismatch** — the SPA sends `"approve"/"deny"`, the executor requires `"approved"/"denied"` (latent bug surfaced while drafting Slice 0). | Normalized at the restored HTTP boundary (`ResolveBody`/`BulkResolveBody`); contract test covers both spellings. | S0.1 §discrepancies |
| R9 | **Playwright flakiness / CI time.** | Chromium-only; few long journeys instead of many small ones; temp-home webServer per run; trace-on-retry. | S0.4, S1.9 |
| R10 | **Vite major bump breaks the build.** | Bump lands behind the build + E2E gates with the lockfile committed; residual advisories dispositioned in writing. | S0.9 |
| R11 | **Held-out suite quietly becomes training data** (the circular-eval failure mode returning). | `examples/heldout/` cases are never fed to the designer prompt or feedback rules; the acceptance runner and the generator share no example source; the 8 review captures stay verbatim as canaries. | S1.5 |
| R12 | **Slice scope creep toward the mesh/platform story.** | The not-in-scope list below is part of the approved plan; changes require editing `00-OVERVIEW.md` first. | everywhere |

## Not in scope (deliberate, decided — not an oversight)

- **Mesh buildout:** process supervision, launchd installation, per-domain agent
  runtimes, cross-platform lifecycle. Mesh stays experimental with demoted,
  honest claims (S0.7) until real retention demands it (review recommendation).
- **Open pack registry / marketplace.** Curated gallery only; Slice 4 is a
  *preview* of the ecosystem, not a launch of one.
- **Signed desktop app, mobile capture, remote access, hosted sync.**
- **Telemetry of any kind** — including opt-in metrics (decision #8).
- **Telegram / Hermes as required Gate-1 adapters.** They remain supported only
  if they pass the same conformance suite; v0.1's required set is CLI + packaged
  SPA + MCP.
- **Storage refactors** (single-DB merge, Postgres). SQLite ×2 stays.
- **Agent protocols beyond MCP** (ACP etc.) and **subscription-runtime ambient
  discovery** (explicit adapters may come after MCP is green).
- **Per-domain custom React code.** The shell stays universal; domain depth comes
  from declarative capabilities (decision #10).

## Human gates (the user's, not the implementer's)

From [`../../LAUNCH_CHECKLIST.md`](../../LAUNCH_CHECKLIST.md) and
[`../OPEN_GATES.md`](../OPEN_GATES.md) — the plan builds *to* these, never
executes them:

1. Name availability final call + claiming `domain-foundry-*` on PyPI.
2. TestPyPI / PyPI publish, git tag, GitHub release (scripts prepared in S1.7).
3. Demo recording (storyboard prepared in S1.10).
4. Launch posts (`docs/launch/` drafts exist).
5. Open gate 4: mesh flags + live Telegram QA (experimental track, unblocked from
   this plan).
6. Open gate 5: Japanese + food cutover decision.
7. Open gate 6 / Slice 2: the ≥7-day Roamboard shadow streak and the cutover
   call.
8. Slice 4: recruiting external design partners, authors, and the security
   reviewer.

## Verification matrix

| Level | What runs | When |
|---|---|---|
| Per-PR | `pytest` (all suites) · `ruff check` · `pyright` · `npm run build` · `npm run lint` (once S1.9 lands) · Playwright E2E (once S0.4 lands) | Every PR, in CI |
| Slice 0 proof | The S0.4 activation journey flips red→green on the restoring PR; zero 410-asserting tests remain for advertised features; `scripts/release_audit.sh` green from a clean shell with its own temp home | Slice 0 exit |
| Slice 1 proof | `scripts/clean_machine_gate.sh` green on macOS + Linux from the built wheel; `doctor` green; Gate-1 journey through CLIDriver + HTTPDriver + MCPDriver; Playwright journey against the *packaged* SPA; wizard held-out suite ≥0.90 (8 review captures handled); ask eval green incl. adversarial cases; TestPyPI dry-run executed | Slice 1 exit |
| Slice 2 proof | Preview→commit idempotency; `/api/apply` policy gating; reshape rollback round-trip; ≥7-day zero-diff shadow streak; filmed trip walkthrough | Slice 2 exit |
| Slice 3 proof | Two golden-outcome demonstrations with real data; the "new similar domain without core edits" test | Slice 3 exit |
| Slice 4 proof | External-party lifecycle run; conformance kit parity with CI; security review report | Slice 4 exit |
| Continuous | `nightly-eval.yml` live-provider drift; `leakscan.yml`; `scripts/docs_claims_check.py` inside the release audit (S0.6) | Nightly / every audit |

## Final release standard (unchanged from the review)

> A person who did not build the repository can install a public artifact,
> connect an agent or use the no-key demo, describe one hobby, see a
> domain-appropriate app, log/import real data, correct a mistake, understand
> where the data went, restart safely, and reproduce the proof themselves.

Every slice exit is a step toward answering this sentence "yes" without
qualification; nothing in this kit is done until its exit evidence exists.
