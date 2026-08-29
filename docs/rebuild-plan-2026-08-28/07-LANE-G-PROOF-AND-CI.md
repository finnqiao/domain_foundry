# Lane G: Proof and CI (M4, WS9)

**Goal:** the pipeline earns the showcase, and the release gate becomes executable. Four gates: the showcase gate (proof #1), the difference gate (proof #2), the minimal fork E2E (proof #3), and the stranger-passion E2E (proof #4). Proof #5 lives in Lane A. This lane runs throughout: gates land early as stubs against current behavior, then flip to enforcing as the other lanes merge.

**Size:** S to M spread across the whole schedule. **Start:** after Phase 0. **Final green requires** B, C, E, F merged.

## Teardown evidence this lane answers

| Finding | Location (verified 2026-08-27; re-locate by content on drift) |
|---|---|
| Interest-to-spec has never been proven end to end; every pipeline test feeds canned stub responses | `tests/unit/test_foundry_pipeline.py:14` (`SequenceProvider`) |
| All five showcase bundles are hand-authored targets with `generation: null` | `examples/showcase/*/README.md` ("TARGET ARTIFACT") |
| The honest gap-closer exists but is manual and not in CI | `scripts/build_showcase.py:2-6` |
| The live smoke never runs the foundry pipeline | `tests/contract/test_llm_live_smoke.py` |
| `parent_spec` is declared with zero writers; `dump_foundry_spec` refuses overwrite | `foundry/models.py:191`, `foundry/loader.py:82-83` |
| Spec-to-app is well proven and must stay that way | `tests/contract/test_foundry_cli.py:29`, `app/e2e/foundry-goldens.spec.ts` |

## Files owned

`scripts/build_showcase.py` · `scripts/foundry_difference_gate.py` (new) · `scripts/showcase_score.py` (new) · `tests/e2e-foundry/` (new: gate tests and cassettes) · `core/domain_foundry_core/foundry/fork.py` (new) plus `cli_fork.py` (new) · `examples/showcase/` regenerated comparison artifacts

**Hidden-path caution:** CI wiring lives in `.github/workflows/`. Do not create or edit anything there without the maintainer's explicit per-file approval. Until approved, every gate is runnable locally and hooked into `scripts/release_audit.sh`.

## Determinism strategy

Live model output is not deterministic; CI must be. Each gate runs in two modes: **cassette replay** (recorded request/response pairs, deterministic, the CI default; the `CassetteProvider` already exists in `llm/provider.py`) and **live opt-in** (`DOMAIN_FOUNDRY_LIVE_GATE=1`, run by a human or a scheduled job before release, refreshing cassettes). A gate passing on cassettes plus at least one recorded live pass before tagging is the release standard; the receipt of the live pass is committed as evidence.

## Phases

### G1: the showcase gate (proof #1)

- [ ] `showcase_score.py`: score a generated spec against its hand-authored target on named axes: entity coverage (target entities present or justified absent), workload naming (each workload traces to the brief), region variety (more than one region kind, topology fits the traits), evidence discipline (every claim tiered and marked), reference closure (already enforced by the model validators). Output a plain scorecard; thresholds recorded in the script header.
- [ ] `build_showcase.py` graduates: run the live pipeline (cassette or live) for the five showcase interests, write the generated spec beside the target, score it, exit non-zero under threshold.
- [ ] Record initial cassettes with the live pipeline once Lanes E and F are in; before that, land the gate red-annotated (the fail-first protocol from the 2026-08 kit: the failing gate documents the gap executable-ly).
- [ ] Gate: scored run green on cassettes for all five showcases; one recorded live pass.

### G2: the difference gate (proof #2)

- [ ] `foundry_difference_gate.py`: build two golden apps (pick the two most structurally distant, sourdough-lab and japanese-study-coach), then assert: DOM topology difference above threshold (distinct `data-topology`, differing region-kind sets, differing landmark structure), token distance above threshold (palette and type stack not near-identical), screenshot difference above threshold at desktop and 390px, and the standing floors (axe serious/critical zero, no horizontal overflow at 320px).
- [ ] Land red-annotated against today's compiler; flip to enforcing when Lane B's B3 merges. This gate is also the trigger for Lane A to restore the Studio's "structurally different" sentence.
- [ ] Gate: enforcing and green after B3; thresholds documented in the script.

### G3: the stranger-passion E2E (proof #4)

- [ ] `tests/e2e-foundry/test_stranger_passion.py`: from a clean workspace, seed the tidepool xlsx fixture and the field-guide HTML fixture (Lane E), consent to model knowledge (Lane F), propose, choose a concept, build, and assert: the app opens with the seeded history inside (record count matches the fixture), evidence distinguishes the user's guide from model claims, and no five-field generic shape appears.
- [ ] Cassette replay in CI; live opt-in refreshes.
- [ ] A second, cheaper case: an out-of-corpus interest with no seeds and no consent still fails closed with the three-path message (the honesty floor).
- [ ] Gate: green on cassettes; one recorded live pass.

### G4: minimal fork (proof #3)

Adopted per the flagged recommendation; if the maintainer drops proof #3, delete this phase and remove the row from the release gate. Nothing else depends on it.

- [ ] `foundry/fork.py`: `fork <spec-or-bundle> [new-id]` copies a spec, assigns a new id, writes `parent_spec` (first writer in the repo), and stamps the fork event into the generation receipt. `dump_foundry_spec`'s refuse-to-overwrite stays; fork is the sanctioned way to derive.
- [ ] `cli_fork.py`: the verb, with one plain sentence of output naming the parent.
- [ ] `foundry validate` accepts a forked spec; the bundle README states the parentage in one line.
- [ ] E2E: fork the sourdough golden, change the accent token and one workload, build, and assert the receipt records the parent and the app reflects the change.
- [ ] Gate: E2E green. Full lineage machinery (iterate history, gallery, "start from this" surfaces) stays P2; do not build it here.

### G5: assemble the release checklist

- [ ] Add all four gates to `scripts/release_audit.sh` behind a `--rebuild-gates` flag first, then default-on once all are enforcing.
- [ ] Write `docs/rebuild-plan-2026-08-28/RELEASE_CHECKLIST.md`: the five proofs with their commands, the standing gates, and the human gates, each with an evidence column to fill in (a green run id, a receipt hash, a recording path).
- [ ] Walk it top to bottom on the final tree; every row green with evidence is the definition of "release-ready". Publishing itself stays human per `LAUNCH_CHECKLIST.md`.
- [ ] Gate: the walked checklist, committed with evidence filled in.

## Definition of done

`scripts/release_audit.sh` (with rebuild gates on) is a single command that proves the five-proof release gate on cassettes, and each gate has at least one recorded live pass committed as evidence. The demo path (the "real June" run) is unblocked: everything the story's scenes need exists and is tested.

## Out of scope

CI workflow file edits without per-file approval. The full lineage system (P2). Performance benchmarks. Publishing.

## Resume notes

(append here)
