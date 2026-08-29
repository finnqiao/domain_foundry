# Rebuild Plan 2026-08-28: Overview

**Status:** Plan of record for the v0.1 open-source release, authored 2026-08-28.
**Sources:** The full-codebase teardown of 2026-08-27 (three sweeps: served app, asset layer, generation engine), the maintainer's marked-up decision quiz and priority board of 2026-08-28, the target user story "June at Low Tide", and the approved plan v3.
**Audience:** A team of agents (or humans) executing lanes in parallel. Each lane doc is self-contained; read this overview first, then only your lane.

---

## What this kit is

The teardown proved one sentence: the spec chain is real, but everything a user touches is a chat box in front of one fixed template. The maintainer graded ten workstreams; the P0 set becomes this kit. The work is organized into seven parallel lanes (A through G) plus a serial contracts phase, so multiple agents can run at once without touching the same files.

| Doc | Lane | Milestone | One line |
|---|---|---|---|
| [`00-OVERVIEW.md`](00-OVERVIEW.md) | | | This file: decisions, rules, lane map, parallel protocol, release gate |
| [`01-LANE-A-TRUTH-AND-VOICE.md`](01-LANE-A-TRUTH-AND-VOICE.md) | A | M0 | Claims audit in CI, dead surface removed, plain-language copy pass |
| [`02-LANE-B-EXPERIENCE-COMPILER.md`](02-LANE-B-EXPERIENCE-COMPILER.md) | B | M1a/b | Spec fields reach pixels; five topologies; bounded bespoke CSS |
| [`03-LANE-C-TASTE-AND-REVIEW-LOOP.md`](03-LANE-C-TASTE-AND-REVIEW-LOOP.md) | C | M1c | The HTML review loop; `look`, `tokens`, `vibe`; approved looks bind |
| [`04-LANE-D-PACK-COMPOSITION.md`](04-LANE-D-PACK-COMPOSITION.md) | D | M2 | `extends`/`imports` between packs; cross-pack links become real FKs |
| [`05-LANE-E-SEED-PIPELINE.md`](05-LANE-E-SEED-PIPELINE.md) | E | M3a | One `seed` command; spreadsheets and exports in; apps born full |
| [`06-LANE-F-BREADTH-AND-GRAPH.md`](06-LANE-F-BREADTH-AND-GRAPH.md) | F | M3b/c | Marked model knowledge; the trait graph; the generic fallback dies |
| [`07-LANE-G-PROOF-AND-CI.md`](07-LANE-G-PROOF-AND-CI.md) | G | M4 | Showcase gate, difference gate, stranger-passion E2E, minimal fork |
| [`08-P1-SHELF.md`](08-P1-SHELF.md) | | post-v0.1 | The merge (WS6), pattern shelf (WS4), backend seam (WS8), contribute loop (WS11) |

**These documents change nothing by themselves.** Work happens in PRs that cite them. Line references were verified against the working tree during the 2026-08-27 sweeps; if a quoted location has drifted, re-locate by content before editing and note the drift in your PR.

## Relationship to earlier plan kits

- [`../build-plan-2026-08/`](../build-plan-2026-08/) (2026-08-10) predates the Foundry redesign. Its Slice 0 truth-pass philosophy and fail-first E2E protocol carry forward; its slice content is superseded where it overlaps this kit.
- [`../UNIVERSAL_CREATE_RELEASE_PLAN.md`](../UNIVERSAL_CREATE_RELEASE_PLAN.md) is the design reference for the wizard/foundry merge. That merge is **WS6, P1**: it is deliberately not in this kit's v0.1 scope. Do not start it inside these lanes.

## Decision record (locked 2026-08-28)

From the maintainer's marked-up quiz and priority board. Not to be re-litigated inside PRs; changing one requires updating this file first.

1. **The substrate is the core value** (Q1=B). Schemas, capture, correction, provenance. Looks and remix are the layers that attract and keep people. Never trade substrate quality for surface features.
2. **True merge is right but not release-blocking** (Q2=C, WS6=P1). All v0.1 work lands on the current foundry path. The merge follows and inherits finished behavior.
3. **Rendering before bespoke** (Q3=C). The compiler renders the spec's experience fields first; the model's bounded bespoke layer builds on that frame.
4. **CLI-first, local-only, BYO key** (Q4). Every capability is a CLI verb. The web studio never has powers the CLI lacks. Nothing hosted, no accounts, no telemetry.
5. **Taste inputs:** editable tokens, binding looks, vibe import (Q4 picks 1, 2, 4). Direct manipulation inside the running app is WS10=P2, not in this kit.
6. **Remix is staged; lineage machinery is P2** (Q5=D, WS3=P2). A **minimal `fork`** ships in v0.1 to satisfy release proof #3 (Lane G). This adopts the maintainer's flagged recommendation; if he reverses it, delete G4 and drop proof #3 from the gate, nothing else changes.
7. **Pack composition is in** (Q6=A, WS5=P0). `extends`/`imports` plus compiled cross-pack foreign keys.
8. **Every breadth on-ramp** (Q7=D, WS7=P0), aimed at the "if this, then that" trait graph rather than indexing every passion.
9. **All five release proofs are blocking** (Q8, WS9=P0). See the release gate below.
10. **Backend stays single-file for v0.1** (Q9=D, WS8=P1). The compiler-target seam and served-SQLite land after release.
11. **The interest graph** (WS11, newly scoped): the **local** trait graph ships in v0.1 inside Lane F. The cross-user contribution loop (`contribute`) is P1, adopted at the proposed grade pending the maintainer's confirmation. The sharing line below is binding either way.
12. **Seed is the hidden center** (story notes). Apps are born full from records the user already keeps. The `seed` command is P0 (Lane E).

## Non-negotiables (apply in every lane)

**Copy and voice.** Every user-facing string follows these rules, and Lane A enforces them:

- Plain conversational language, TLDR first, no jargon. Write like talking to a colleague who is not an engineer.
- No em dashes anywhere in user-facing copy or docs.
- Never mention costs, pricing, "free", or paid upgrades. Defaults simply work without paid services. Paid options are discussed only if the user raises them.
- No clever or poetic lines. "The page you'd open to settle an argument" is the canonical failure. Simple words only.
- Every ask names exactly what to provide. "A spreadsheet you keep, a notes folder, a field guide page." Never a vague request for "sources".
- App ideas are pitched the way a friend would: "Want to log every nudibranch you see? You already have a log of observations and dates. Build a Pokedex-style tracker for it." One line of design and feel after. The engineering spec stays available underneath, never as the pitch.

**Honesty.** Fail-closed labels, provenance validation (`provenance_is_unmistakable`), the compiler-supplied independent evaluation, hashed receipts: untouched, and extended to every new surface. Model-derived content is always marked so the user can tell it apart from their own sources.

**The sharing line** (binding for Lane F's local graph and the P1 contribute loop):

| Shared, only after a preview page and an explicit yes | Never shared, under any setting |
|---|---|
| Public reference links the user seeded, with what they cover and their license | Any row or record from personal uploads: spreadsheets, mail, notes, app exports |
| Schema shapes: table and field names, types, connections | Photos and files |
| Learned trait rules ("driven by the moon, then time windows") | Personal vocabulary from their data: spot names, dates, counts, notes |
| Layout and view choices that worked | Keys, settings, machine details |

Rule of thumb, stated on every preview page: shapes and public links can travel; your records never do. Anything derived from a personal upload counts as personal, even when it looks like a harmless list.

**No dead surface area.** A spec field nothing reads, an endpoint nothing calls, a claim the code cannot keep: each is a release blocker, enforced by Lane A's claims audit on every PR.

## Lane map and file ownership

Parallel safety comes from exclusive file ownership. A lane may freely edit its owned files. Shared files have a named rule. Anything else is out of bounds; if you believe you must touch another lane's file, stop and write it in your resume note instead.

| Lane | Owns (exclusive) | Depends on |
|---|---|---|
| A | `README.md`, `docs/` copy, `app/src/components/FoundryStudio.tsx` copy strings, CLI prompt strings, `scripts/claims_audit.py` (new), `tests/contract/test_claims_audit.py` (new) | Phase 0 |
| B | `core/domain_foundry_core/foundry/compiler.py`, `core/domain_foundry_core/foundry/runtime.js`, `tests/contract/test_foundry_compiler.py` | Phase 0 |
| C | `core/domain_foundry_core/wizard/looks.py`, `core/domain_foundry_core/review/` (new package), `core/domain_foundry_core/cli_taste.py` (new), related tests | Phase 0; binds through contracts, not through Lane B's files |
| D | `core/domain_foundry_core/packs/loader.py`, `core/domain_foundry_core/packs/models.py`, `core/domain_foundry_core/packs/schema_compiler.py`, `scripts/pack_conformance.py`, `packs/_template/`, related tests | Phase 0 |
| E | `core/domain_foundry_core/seed/` (new package), `core/domain_foundry_core/cli_seed.py` (new), `examples/seed-fixtures/` (new), related tests | Phase 0 |
| F | `core/domain_foundry_core/foundry/research.py`, `core/domain_foundry_core/atlas/` (graph additions), `core/domain_foundry_core/wizard/blueprint.py` (fallback death only), `knowledge/` docs, related tests | Phase 0; consumes Lane E's `SeedProvenance` contract |
| G | `scripts/build_showcase.py`, `scripts/foundry_difference_gate.py` (new), `.github/workflows/` additions (**hidden path: requires the maintainer's per-file approval before any edit**), `tests/e2e-foundry/` (new), cassettes, `core/domain_foundry_core/foundry/fork.py` (new), related tests | Runs throughout with stubs; final green needs B, C, E, F merged |

**Shared-file rules:**

- `core/domain_foundry_core/foundry/models.py`: extended once in Phase 0 with every new type this kit needs. After Phase 0 it is frozen for this kit; a lane needing a model change files it with the integrator (a one-commit change, rebased by all lanes) instead of editing directly.
- `core/domain_foundry_core/cli.py`: lanes never add logic here. Each lane ships its own `cli_<name>.py` module; `cli.py` gets one registration line per lane, added at the sync points below by the integrator.
- `pyproject.toml`, `mkdocs.yml`: integrator-only, at sync points.

## Execution protocol

**Phase 0 (serial, one agent, first PR).** Land the shared contracts so every lane codes against real types:

- [ ] `models.py`: add `BespokeLayer` (validated per-app CSS envelope: allowed properties, size budget), `LookBinding` (chosen look id, token overrides, borrowed fragments), `SeedProvenance` (source kind: personal upload vs public link; personal is never shareable), `TraitEdge` (trait, consequence, evidence id), `parent_spec` write semantics (type exists today at `models.py:191` with zero writers).
- [ ] `cli.py`: add the subcommand registry hook so lanes register `cli_<name>.py` modules with one line each.
- [ ] `tests/unit/test_contracts_2026_08_28.py`: round-trip every new type through validation.
- [ ] Gate: full suite green with exact counts reported; no behavior change anywhere.

**Fan-out.** Lanes A through G start in parallel after Phase 0 merges. Branch naming: `rebuild/lane-<letter>-<slug>`.

**Sync points (integrator merges, in order):**

1. **SP1** after A1 and any lane's first phase: claims audit lands in CI so later PRs are checked by it.
2. **SP2** when B and C are both at their binding phases: C's `LookBinding` output compiles through B's compiler. One integration test, owned by C.
3. **SP3** when E and F are both done: seeded provenance flows into research marking. One integration test, owned by F.
4. **Final:** Lane G flips its gates from stub to real and the release checklist below is walked top to bottom.

**Per-agent working rules** (from the repo's own conventions):

- Before committing, `git fetch && git status`; never build on a stale baseline.
- Commit-sized chunks; after each chunk run the full suite and report exact pass counts (for example `801/801`). A lane phase is not done on a partial run.
- Write a short resume note at the end of every session (what landed, what is next, any cross-lane requests) at the bottom of your lane doc under "Resume notes".
- No destructive git operations. Never touch another lane's owned files. Never create or edit dotfiles or workflow files without the maintainer's explicit per-file approval.
- All new user-facing strings follow the copy rules above; expect Lane A's audit to check them.

## Release gate (all five, plus the standing gates)

v0.1 is releasable when every row is green with evidence:

| # | Proof | Enforced by | Lane |
|---|---|---|---|
| 1 | The pipeline generates a showcase-caliber spec unaided, in CI | `build_showcase.py` graduates to a scored gate | G |
| 2 | Two generated apps for different passions are visibly, structurally different | Difference gate: DOM topology diff, token distance, screenshot diff, axe clean, no 320px overflow | G (consumes B) |
| 3 | A real fork path end to end, parentage recorded | Minimal `fork` E2E | G |
| 4 | An out-of-corpus passion, seeded from a spreadsheet fixture, yields an honest, marked, usable app | Stranger-passion E2E, cassette-replayed plus opt-in live | G (consumes E, F) |
| 5 | README matches code: no dead fields, no ghost surfaces | Claims audit on every PR | A |

Standing gates stay as they are: `scripts/release_audit.sh`, leakscan, clock audit, license and SBOM audits, `quickstart_gate.sh`. Human gates are unchanged and still block the public tag: name clearance (ADR-005), external security review, demo recording (the "real June" run from the user story), screen-reader pass, package publication.

## The target to keep in view

The user story "June at Low Tide" is the acceptance narrative: an out-of-corpus passion, seeded from a spreadsheet, three ideas pitched like a friend would, a marked-up review page that binds into the build, an owned offline app with the user's history inside, a correction that keeps its past, a stack with a real join, and a fork that knows its parent. Ship test: a real person does this with nobody in the room.
