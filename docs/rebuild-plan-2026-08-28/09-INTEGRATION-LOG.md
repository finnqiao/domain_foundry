# Integration log

The integrator's record. Lanes append to their own doc's Resume notes; this file
records what the integrator did to the shared files, in order, with the suite
count at each step.

Shared files, integrator only: `core/domain_foundry_core/cli.py` (one
registration line per lane), `core/domain_foundry_core/foundry/models.py`
(frozen after Phase 0), `pyproject.toml`, `mkdocs.yml`,
`core/domain_foundry_core/foundry/pipeline.py` (stage prompts, no lane owns it).

Hidden paths, maintainer only: anything under `.github/`, and every other file
whose path has a component starting with a dot. Lanes write the snippet they
want pasted; nobody in this kit edits those files.

---

## Baseline

| When | What | Suite |
|---|---|---|
| Before Phase 0 | `main` at `1573fc4` | 780/780 green, 1 skipped |

## Phase 0 (serial, integrator)

Commit `22c5904` on `rebuild/2026-08-28`.

- `foundry/models.py`: added `BespokeLayer`, `BorrowedFragment`, `LookBinding`,
  `SeedProvenance`, `TraitEdge`, the named vocabularies (`NavigationTopology`,
  `TypographyStack`, `DensityScale`, `SignatureElement`) with plain-language
  labels, and the `BESPOKE_*` envelope constants.
- Attachment points, all optional so the three goldens load unchanged:
  `VisualWorld.typography_stack`, `VisualWorld.density_scale`,
  `VisualWorld.signature_element_ids`, `VisualWorld.bespoke`,
  `ResearchBrief.seeds`, `ResearchBrief.traits`, `FoundrySpec.look`.
- `RemixSelection.parent_spec` now validates as a spec id, ready for `fork` to
  become its first writer.
- `cli.py`: `LANE_CLI_MODULES` plus `register_lane_commands()`. Lanes ship
  `cli_<name>.py` with `register(app)`; the integrator adds one line here.
- `tests/unit/test_contracts_2026_08_28.py`: 27 tests round-tripping every new
  type and proving the goldens still load.
- `docs/prototypes/*.html` regenerated (they embed spec JSON and are audited for
  staleness by `tests/unit/test_foundry_audit.py`).

Suite: **807/807 green** (780 before, 27 new).

## Fan-out

Lanes A through G started in parallel after Phase 0. Each lane owns an exclusive
file set and ships its own `cli_<name>.py`.

| Lane | CLI module to register | Status |
|---|---|---|
| A | (none; edits prompt strings in place) | **done**; `cli.py` released |
| B | (none) | **done** (B1 to B6 plus follow-up); difference gate closed at 8/8 |
| C | `cli_taste` | **done and registered** (`look`, `tokens`, `vibe`) |
| D | `cli_stack` | **done and registered** |
| E | `cli_seed` | **done and registered** |
| F | (needs one `foundry propose` flag change, see its Resume notes) | running |
| G | `cli_fork` | **done and registered** (`foundry fork`); gates red-annotated as designed |

## Sync points

| SP | Trigger | Owner of the integration test | Status |
|---|---|---|---|
| SP1 | A1 lands: claims audit runs on every PR | Lane A | **green locally**: `claims_audit.py --strict-allowlist` exits 0, wired into `release_audit.sh` as check 17. CI step is YAML in A's resume notes, for the maintainer to paste. |
| SP2 | B and C both at their binding phases: a `LookBinding` compiles | Lane C | **green**: `tests/contract/test_look_binding_compiles.py`, 6 tests |
| SP3 | E and F both done: seed provenance reaches research marking | Lane F | pending |
| Final | Lane G flips its gates from red-annotated to enforcing | Lane G | pending |

## Cross-lane requests raised by finished lanes

| From | Request | Shared file | Status |
|---|---|---|---|
| E | Register `cli_seed` | `cli.py` | waiting on Lane A to leave `cli.py` |
| E | Offer seeding inline in the create ask (copy ready as `seed.brief.SEED_ASK`) | `wizard/`, `cli.py` | integrator, after A |
| D | Register `cli_stack` | `cli.py` | waiting on Lane A to leave `cli.py` |
| D | Wire `schema_compiler.uninstall_blockers()` into `PackRegistry.uninstall()` | `packs/registry.py` | integrator, unowned file |
| D | Six pre-existing em dashes in `docs/PACK_AUTHORING.md` outside D's section | docs copy | Lane A owns |
| G | Register `cli_fork` | `cli.py` | waiting on Lane A to leave `cli.py` |
| G | Add `tests/e2e-foundry` to `testpaths` **only once all four gates are green**, and delete the `pytest_ignore_collect` guard in its conftest | `pyproject.toml` | integrator, at final |
| G | Bundle README should name the parent spec: one line in `FoundryCompiler.render_readme` | `foundry/compiler.py` | Lane B owns |
| G | Retrieval collision: a tide-pool plan using the word "species" matches the aquarium exemplar's `species_care` topic, so an out-of-corpus passion is labelled `reviewed_corpus` | `foundry/research.py` | Lane F owns |
| C | Register `cli_taste` | `cli.py` | **done** |
| C | `_CRITIQUE_RE` still lives in `wizard/engine.py:117`. Lane C killed the half that was its own (`looks.py`'s keyword restyler), leaving the matcher inert but present. `engine.py` has no owner. | `wizard/engine.py` | integrator, unowned file |
| C | Borrowed fragments reach the built bundle but nothing in the runtime renders them. If that stays true, Lane A's audit should call it dead surface. | `foundry/runtime.js` | Lane B owns |

## Deviations accepted

- **Lane D, pack policy merge.** The lane doc says "policy is child's own". Lane D
  implemented child's-own-when-declared, otherwise inherit the parent's, because
  a stacked pack with no policy of its own could not apply anything. Documented
  in `docs/PACK_AUTHORING.md`. Accepted: it is the only reading that leaves
  `stack` working.
- **Lane D, an additive widening.** Any object carrying a link now gains a
  `{link}_uid` field, so `field_contract` and `schema_registry` are wider than
  before for those objects. Unavoidable: D2 requires links to compile to columns
  the apply engine writes. Additive only, every pack suite green, but a test
  asserting an exact field set on a linked object would see it.

## Integrator steps

| # | What | Result |
|---|---|---|
| 1 | Corrected the seed fixture names in `tests/e2e-foundry/test_stranger_passion.py`. Lane G guessed `tidepool-sightings.xlsx` / `tidepool-field-guide.html`; Lane E shipped `tidepool-log.xlsx` / `field-guide.html`. First real cross-lane seam. | `tests/e2e-foundry` 17/22 to 18/22 |
| 2 | `scripts/docs_claims_check.py`: excluded `docs/rebuild-plan-2026-08-28/`, the way `docs/build-plan-2026-08/` already was. The kit records exact pytest counts from lanes in progress; those are working records, not claims to a reader. | `docs_claims_check` red to OK, 26 files |
| 3 | `cli.py`: registered `cli_seed`, `cli_stack`, `cli_fork` in `LANE_CLI_MODULES`. `seed` and `stack` are top-level verbs; `fork` joins the existing `foundry` group. | `seed`, `stack`, `foundry fork` all live; 92/92 green across the CLI, claims-audit, stack, seed and contract suites |
| 4 | `cli.py`: registered `cli_taste`. `look`, `tokens` and `vibe` are top-level verbs. | 71/71 green across Lane C's suites including SP2; claims audit still OK |
| 5 | Ran the difference gate against Lane B's landed work and sent Lane B a scoped follow-up for the two remaining checks plus the two cross-lane requests filed against its files (Lane G's README parentage line, Lane C's unrendered borrowed fragments). | proof #2 went from 2/8 to **6/8** |
| 6 | Lane B's follow-up closed all four items. Verified independently: difference gate **PASS 8/8**, `tests/e2e-foundry` 19/22 with the three remaining reds all cassette-blocked. | **proof #2 green, proof #3 green** |
| 7 | Flipped Lane F's SP3 fixture test from `xfail` to a plain test. Lane F wrote it as xfail while Lane E's package was still landing; the package imports, so the seam is proved rather than hoped for. | SP3 **green**, 6/6 |
| 8 | `cli.py`: wired `--from-model-knowledge` into `foundry propose`, per Lane F's written request. | Lane F's guard test green |
| 9 | `pipeline.py`: wired the trait graph in (detect traits, `structural_options` in the concepts payload, the concept prompt, `claim_tiers` on the receipt). **Lane F's requested edit as written leaked personal data**: it attached `knowledge.personal_seeds` to the brief, which is dumped into the model payload and kept on the proposal, so a personal upload's filename and column names reached both. Lane F's own SP3 test caught it. Corrected to attach traits only: the shapes travel, the records do not. | SP3 green; `enrich_brief`'s own docstring now matches what the pipeline does |
| 10 | Retargeted five tests that used out-of-corpus goals ("cocktails", "lego builds") as throwaway fixtures for testing coercion, corrections and the first-note gate. Lane F's death of the generic fallback made them refuse. Followed Lane F's own precedent and moved them to a real archetype, aligning the fake payloads with the `coffee` schema so they measure what they claim to. | 5 failures cleared |
| 11 | `packs/registry.py`: wired `uninstall_blockers()` into `PackRegistry.uninstall()`, Lane D's cross-lane request. Added `test_the_registry_refuses_to_uninstall_a_pack_records_still_point_at`, because the function was proved but the wiring was not: a real uninstall would still have broken the references. | 21/21 in the composition suite |
| 12 | `mkdocs.yml`: added `COPY_RULES.md` to the nav and moved three internal records out of the public Concepts nav, per Lane A. Fixed a broken link Lane G's `RELEASE_CHECKLIST.md` introduced (`LAUNCH_CHECKLIST.md` sits at the repo root, outside the docs site). | `mkdocs build --strict` exits 0 |
| 13 | `models.py`: removed the em dashes from `EVIDENCE_TIER_LABELS`, which Lane F flagged and which no lane could reach. Updated the four tests pinning those exact sentences. | copy rules hold in the frozen file too |
| 14 | Brought `RELEASE_CHECKLIST.md` up to date: proofs 2, 3 and 5 are green with the measured numbers, and proofs 1 and 4 are each waiting on exactly one thing, a recorded live run. | the checklist now describes the tree |
| 15 | Wizard copy sweep (delegated). All ten wizard modules swept; the five copy contracts in `release.py` moved in lockstep and still fire. Every `"not yet: integrator, wizard copy sweep"` allowlist entry deleted; the copy section now holds one permanent exception, the rules page itself. | claims audit green with an empty copy backlog |
| 16 | `scripts/leakscan.py`: Lane E's fixtures tripped it. Allowed `.xlsx` **only** under `examples/seed-fixtures/` rather than globally, since an xlsx is a zip and can carry anything, and added `@example.invalid` to the synthetic-email suffixes (RFC 6761 reserves `.invalid`, so it can never be a real address). | `leakscan findings: 0` |

## Known red, to clear at the final sync

- `tests/unit/test_foundry_audit.py`: "committed prototypes were stale". The
  prototypes embed spec JSON and are regenerated by
  `scripts/build_foundry_prototypes.py`. A lane changed the compiler or a golden
  after Phase 0 regenerated them. Regenerate once Lane B is finished, not before,
  or it will just go stale again.
- `tests/e2e-foundry`: 3 red, all waiting on recorded cassettes, which need a
  key and a network. `test_showcase_cassettes_are_recorded`,
  `test_stranger_passion_cassettes_are_recorded` and
  `test_seeded_app_opens_with_the_users_history_inside`. These are the
  maintainer's live-recording run, not a code gap.


## Open findings for the maintainer

Two things were investigated and deliberately left alone. Both are written up
here because a quiet "done" would have been the wrong answer.

### 1. `_CRITIQUE_RE` is not dead, and should stay

Lane C reported that `_CRITIQUE_RE` in `wizard/engine.py` was inert after it
removed the keyword restyler in `looks.py`, and asked for it to be deleted.
That premise is wrong, and deleting it would have changed behaviour:

- Template path: `looks.py` still does `hints = hints + hinted_jobs(critique)`,
  and `hero_job` uses those hints to pick the hero, which selects a different
  `_hero_body`. Measured: the same idea with no critique picks hero
  `improvement`; with the critique "make it more photos" it picks `media_dex`,
  which is different HTML. `engine.py` independently adds `hinted_jobs(text)`.
- Designer path: with a designer model configured, the critique text goes into
  the payload as `CRITIQUE` with `PREVIOUS_HTML_PRESENT` set.

What Lane C actually removed was the tone and colour guessing, which is the
half that should have died: colours are chosen on the review page now, never
guessed from words like "darker". The critique loop that re-picks the hero view
is the useful half and it survived. No change made.

### 2. The no-key create path never names a field after the interest

Lane F could not close the generic-scaffold route and flagged it as belonging
to nobody in this kit. Investigated: **it is larger than Lane F reported**, and
it is the one real gap left in the release story.

- `build_blueprint` is **bypassed entirely** on the wizard's normal path. Its
  only caller is `_design_and_propose` (the `design_mode: "scaffold"` route).
  So the archetypes in `blueprint.py` never fire for a wizard create, and
  neither does `GenericFallbackRefused`. A goal with "a real archetype" still
  lands on `['name', 'noted_at', 'value', 'notes']` through the wizard.
- `jobs.py::shortlist_for_ideas` builds the field list **structurally, from job
  ids only**: `<slug>_name`, `noted_at`, `notes`, plus `photos` / `location` /
  a measure when the jobs call for them. It never derives a field name from the
  goal, from the atlas node, or from the user's seed sentences. The shape is
  generic by construction.
- This is not an unindexed-goal problem. It is the whole no-key path. Seven
  goals run through the shipped flow, scored with the eval's own
  `GENERIC_FIELDS`:

  | goal | specific fields |
  |---|---|
  | track my origami | `logged_at` only |
  | diving | `lat`, `lng` |
  | rock tumbling batches | none |
  | metal detecting finds | none |
  | keep a coffee brewing log | none |
  | log the board games we play | none |
  | the REVIEW_8 climbing case | none |

  `"xyzzy plugh foobar"` reaches `test_drive` with
  `['xyzzy_name', 'noted_at', 'photos', 'notes']`. In the rock-tumbling case
  the user had already given two seed sentences full of real vocabulary
  ("split the creek haul into agates and junk", "moved the barrel to stage two
  grit") and none of it named a field.

**Why nothing was changed.** Two fixes exist. (a) Make `shortlist_for_ideas`
derive field names from the seed sentences and the atlas node: that is Lane B
and Lane E work, not a gate. (b) Gate activation on "every field name comes
from the wizard's own vocabulary" and raise the three-path message otherwise:
that refuses nearly every no-key create, not the nine unindexed ones, and
would break tests that pin real behaviour rather than stale copy
(`test_origami_scaffolds_without_key`,
`test_picked_idea_compiles_when_analog_is_not_1_to_1`,
`test_proof_loop_starters_and_new_interest` and the capture-correct-export
chain after it, all eight REVIEW_8 cases, several atlas tests, and the pinned
`wizard_*_suite.jsonl` baselines). It is also incoherent as an experience: the
wizard asks for two seed sentences first, then would answer "seed something you
keep".

**Recommendation.** Scope this as its own piece of work before the v0.1 tag, as
(a). Lane F's regrading already refuses to call the current output a success,
so the held-out numbers are honest today; what is not yet true is the product
claim that an app is shaped by the interest it was built for. The claims audit
should carry an entry naming this until it is fixed.
