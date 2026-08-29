# Lane A: Truth and Voice (M0)

**Goal:** the repo tells the truth in plain words. Every claim maps to code, every dead surface is removed or labeled, and every user-facing string follows the copy rules in the overview. This lane also builds the audit that keeps it true for every later PR.

**Size:** S (days). **Start:** immediately after Phase 0. **Blocks:** release proof #5.

## Teardown evidence this lane answers

| Finding | Location (verified 2026-08-27; re-locate by content on drift) |
|---|---|
| `ImplementationSpec.targets` includes `standalone_react`, declared and read nowhere | `core/domain_foundry_core/foundry/models.py:425` |
| Studio claims "structurally different applications, not color variants"; measured difference is 9 hex values and one topology flag | `app/src/components/FoundryStudio.tsx:277` |
| SSE endpoint yields two frames and is called by nothing | `core/domain_foundry_core/api/app.py:960-974` |
| `VisualWorld` fields (`typography`, `density`, `layout_principle`, `signature_elements`, `avoid`) have zero readers | `foundry/models.py:295-306` vs `foundry/compiler.py`, `foundry/runtime.js` |
| Wizard `/create` is a message stack labeled "Your guide"; docs imply it is the flagship generator | `app/src/components/CreateDomain.tsx:242` |
| CLI copy is engineer-facing in places; asks are vague | `cli.py` prompt strings, `wizard/` turn copy |

## Files owned

`README.md` · `docs/` copy (not other kits' plan files) · copy strings in `FoundryStudio.tsx` and `CreateDomain.tsx` (strings only, no logic) · CLI prompt strings · `scripts/claims_audit.py` (new) · `tests/contract/test_claims_audit.py` (new) · `docs/COPY_RULES.md` (new)

## Phases

### A1: the claims audit (build the enforcement first)

- [ ] Write `scripts/claims_audit.py` with three checks: (1) **spec-field readers**: every field on `VisualWorld`, `ExperienceSpec`, and `ImplementationSpec` either has a reader in `compiler.py`/`runtime.js` or appears in an allowlist file `scripts/claims_audit_allowlist.yaml` with a "not yet: <lane>" reason; (2) **copy rules**: no em dash characters, no cost words ("free", "paid", "pricing", "upgrade") in user-facing strings and docs, allowlist for legitimate uses (LICENSE, third-party notices); (3) **claim map**: every README feature sentence carries a marker comment naming the test or script that proves it, checked for existence.
- [ ] Seed the allowlist honestly: `standalone_react` ("not yet: P1 WS8"), `VisualWorld` fields ("not yet: Lane B"), so the audit is green at birth and shrinks as lanes land.
- [ ] `tests/contract/test_claims_audit.py`: the audit runs clean on the current tree; a fixture with a violation fails.
- [ ] Ask the maintainer to wire the audit into CI (workflow files are hidden-path; do not edit them yourself). Until then, add it to `scripts/release_audit.sh`.
- [ ] Gate: `python scripts/claims_audit.py` exits 0; full suite green with exact counts.

### A2: dead surface removal

- [ ] `standalone_react`: keep the field, make selecting it a clear error ("Not available yet") at spec-load time, and record it in the allowlist. Removing the enum member breaks golden YAML round-trips; the error path is the honest middle.
- [ ] Delete the unused SSE endpoint at `api/app.py:960-974` and its route registration, or wire it to the create flow if Lane C requests it by SP2 (default: delete).
- [ ] Fix `FoundryStudio.tsx:277`: the "structurally different" line becomes true only when Lane B lands; until then it reads "Three different starting points" with no structural claim. After SP2, Lane A revisits and restores the stronger sentence if the difference gate is green.
- [ ] Gate: claims audit still green; suite green with counts.

### A3: the copy pass

- [ ] Write `docs/COPY_RULES.md`: the six copy rules from the overview, with three before/after examples each, including the pitch template ("Want to log every nudibranch you see? You already have a log of observations and dates. Build a Pokedex-style tracker for it.").
- [ ] Sweep every CLI question and status line: TLDR first, concrete asks, no jargon, no em dashes, no cost words. The seed ask names its inputs exactly ("a spreadsheet, a notes folder, photos, an export from another app or your email; one or two pages you trust, like a field guide or a species checklist").
- [ ] Sweep `README.md` and `docs/` user-facing pages with the same rules. Remove internal phase material from the public nav where it still leaks (check `mkdocs.yml` nav through the integrator).
- [ ] Label the `/create` wizard path for what it is until the P1 merge: a quick-capture starter, not the flagship generator. The foundry path is the release story.
- [ ] Gate: claims audit copy check green across the tree; suite green with counts.

### A4: README truth pass

- [ ] Rewrite README claims to match the post-lane reality only as lanes merge (coordinate at sync points; keep a "pending" branch of stronger claims that lands with SP2/SP3).
- [ ] Every remaining claim carries its proof marker.
- [ ] Gate: `python scripts/claims_audit.py` green on the final tree; this is release proof #5.

## Out of scope

Logic changes in the Studio or wizard (Lanes B, C, and the P1 merge). Workflow file edits without per-file approval. Anything in other lanes' owned files.

## Resume notes

(append here)
