# Lane F: Breadth and the Local Interest Graph (M3b, M3c)

**Goal:** an unindexed passion stops being a dead end. Model knowledge joins the default flow, clearly marked so the user can always tell model claims from their own sources. The hard error and the silent five-field fallback both die. Underneath, the atlas jobs vocabulary grows into the local "if this, then that" trait graph that turns one sentence into three structurally different app ideas. This is WS7 (P0) plus the local half of WS11.

**Size:** M (1 to 2 weeks). **Start:** after Phase 0, parallel with everything. **Meets Lane E at SP3.**

## Teardown evidence this lane answers

| Finding | Location (verified 2026-08-27; re-locate by content on drift) |
|---|---|
| Research fails closed on anything outside the registry when no search adapter is configured | `foundry/research.py:238-249` (`ResearchUnavailable`) |
| The 10 domain exemplars are exactly the 3 goldens plus the 5 showcases | `knowledge/source-registry.yaml` |
| `foundry propose` never passes `allow_model_knowledge`; the model-recall tier exists but is unreachable | `cli.py:1500-1502`, `research.py:96-136` |
| The wizard fallback is a five-field generic `entry` log | `wizard/blueprint.py:359-410` (`_generic_spec`) |
| The held-out eval counts the generic fallback as a pass | `examples/heldout/interest_suite_baseline.json` (`honest_miss: 11`, `pass: 50`) |
| The compositional vocabulary is 9 job ids with no trait reasoning | `atlas/models.py:13-23` |
| Topic matching is loose token overlap with a floor of 1 | `research.py:48, 166-212` |

## Files owned

`core/domain_foundry_core/foundry/research.py` · `core/domain_foundry_core/atlas/` (graph model and loader additions) · `core/domain_foundry_core/wizard/blueprint.py` (only the death of `_generic_spec` and its call sites) · `knowledge/` documentation updates · `examples/heldout/` grading updates · related tests

Shared: `TraitEdge` and `SeedProvenance` types from Phase 0. Concept-stage prompt changes go through the integrator (prompts live in `foundry/pipeline.py`, which no lane owns; changes land as small integrator-reviewed commits).

## Design constraints

- Honesty machinery is load-bearing and stays: `provenance_is_unmistakable` (model recall may not carry a URL or claim approved status), fail-closed remains the behavior when the user declines every on-ramp.
- Marking language follows the copy rules: "marked, so you can always tell which is which", never scary or technical.
- The knowledge registry's editorial discipline is unchanged: user seeds are build-local evidence; promotion into the shared registry stays a human editorial act.

## Phases

### F1: model knowledge, marked and reachable

- [ ] `research.py`: the create flow offers three concrete paths when the registry has no vertical match: seed something you keep, seed a page you trust, or "just build" from model knowledge with marking. Wire `allow_model_knowledge` through `foundry propose` behind that explicit user choice (never silently).
- [ ] Model-recall snapshots keep their unmistakable provenance; the compiled evidence page and the app's evidence dialog show the marking in plain words.
- [ ] The receipt records which tier every claim came from.
- [ ] Tests: propose on an out-of-corpus interest with consent succeeds and every model-tier snapshot is marked; without consent it still fails closed with the three-path message.
- [ ] Gate: suite green with counts.

### F2: user seeds join research (SP3)

- [ ] Seeded public links (Lane E) enter the research stage as user-supplied sources: cited, dated, license-unknown-until-reviewed, distinct from both the reviewed registry and model recall.
- [ ] Personal uploads never appear as citable sources; their summaries enter the brief as the user's own artifacts (which is what they are).
- [ ] SP3 integration test (owned here): a brief seeded with the tidepool xlsx and the field-guide URL produces evidence citing the guide, artifacts from the log, and marked model claims, all distinguishable in the output.
- [ ] Gate: SP3 test green; suite green with counts.

### F3: the trait graph

- [ ] `atlas/`: add the graph model on `TraitEdge` (trait, structural consequence, evidence id). First edge set, hand-authored with citations into `knowledge/`: driven by tides or moon or season, then time windows; collected instances, then catalog with owned-versus-gap split; practiced skill, then sessions with one decision at a time; place-bound, then atlas with per-place history; produces artifacts, then media roll with contact-sheet review; improves over time, then trend loop with comparison.
- [ ] Trait detection: the research stage extracts traits from the brief plus seeds (a tide CSV implies time windows; repeated place names imply place-bound) and the concept stage consumes edges so the three concepts differ by structure, not phrasing. Prompt changes via the integrator.
- [ ] Overlay rule stays: user-local graph additions at `~/.domain_foundry/atlas/` merge over shipped files, same-id-wins.
- [ ] Tests: the tidepool brief yields the three story concepts' structures (session-first, place-first, collection-first) in cassette replay; a practiced-skill brief yields session topology.
- [ ] Gate: suite green with counts.

### F4: the generic fallback dies

- [ ] Delete `_generic_spec` and its call sites; the floor for an out-of-corpus interest becomes a marked model-knowledge spec the user consented to, shaped by whatever traits were detected.
- [ ] Regrade the held-out suite: the fallback no longer counts as a pass; "honest miss" (fail-closed with the three-path message) remains a countable, acceptable outcome; a five-field scaffold presented as success is a failure.
- [ ] Update `interest_suite_baseline.json` and the grading code accordingly, with the change explained in the file header.
- [ ] Gate: held-out suite green under the new grading; suite green with counts.

## Definition of done

June's scene 2 and scene 3 work end to end in cassette replay: an out-of-corpus, seeded interest produces marked evidence and three structurally different, trait-driven ideas. The words "five-field generic log" describe nothing in the tree. Lane G's stranger-passion E2E has everything it needs.

## Out of scope

The cross-user contribute loop and its preview page (P1 WS11; the sharing line in the overview binds its design). New reviewed registry entries (human editorial act). Search adapters beyond what exists.

## Resume notes

(append here)
