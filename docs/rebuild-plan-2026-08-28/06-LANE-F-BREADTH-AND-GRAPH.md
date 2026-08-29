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

### F1 done, 2026-08-28

**Landed.** `research.py` now offers three concrete on-ramps instead of one dead
end. `THREE_PATHS` and `three_path_message(interest)` are the copy; the
fail-closed `ResearchUnavailable` raises that message and carries `.paths` so no
caller has to invent its own wording. `MODEL_CLAIM_MARK` and
`MODEL_MARKING_NOTE` are the plain-words marking for the evidence page and the
app's evidence dialog. `RetrievedKnowledge` gained `seeded_ids`,
`personal_seeds` and `tier_of(source_id)`; `claim_tiers(evidence, knowledge)`
turns that into the per-claim map a receipt records.

**Floors held.** No consent still means no build. Model recall still cannot
carry a URL or claim approval. Nothing reaches model knowledge unless a caller
passed `allow_model_knowledge`, and the CLI guard test now pins the stronger
invariant: the CLI may only pass that flag from a user-supplied option, never
from a constant.

**Tests.** `tests/unit/test_breadth_three_paths.py` (7 new). Gate run:
`tests/unit/test_foundry_bridge_pipeline.py`,
`tests/unit/test_foundry_pipeline.py`,
`tests/unit/test_foundry_research_retrieval.py`,
`tests/unit/test_contracts_2026_08_28.py`,
`tests/unit/test_atlas_evidence_floor.py`,
`tests/contract/test_slice3_heldout.py`,
`tests/contract/test_wizard_bridge_escalation.py`,
`tests/unit/test_breadth_three_paths.py` = **115 passed**.

**Other lanes' files touched:** none. Three existing tests changed their
`ResearchUnavailable` match string from `will not present a generic scaffold` to
`Three ways forward` (`tests/unit/test_foundry_pipeline.py` x1,
`tests/unit/test_foundry_bridge_pipeline.py` x2), and
`test_the_propose_cli_never_opts_into_model_recall` was rewritten as
`test_the_propose_cli_never_reaches_model_recall_silently`. Both files are
research/pipeline tests that no lane doc claims.

**Next:** F2.

### F2 done (SP3), 2026-08-28

**Landed.** `KnowledgeRetriever(seeds=...)` (also `retrieve(seeds=...)`) takes
what the user seeded. Public links become cited, dated, unreviewed candidates
via `seed_link_candidates`; their ids are reported separately in
`RetrievedKnowledge.seeded_ids`. Personal uploads never become candidates at
all: `personal_artifact_lines` turns them into plain sentences and `enrich_brief`
attaches them to `ResearchBrief.existing_artifacts` along with
`ResearchBrief.seeds` and `ResearchBrief.traits`.

**One behaviour change worth reviewing.** Model recall used to be reachable only
when a run had nothing else at all. It is now additive: when there is no
reviewed vertical match and the caller opened the gate, recall joins whatever
seeded or searched candidates exist, and the run tier drops to
`model_knowledge`. That is the honest floor. A run holding any unread recall is
never labelled as researched, however much else it also holds, and per-claim
truth stays available through `claim_tiers`. Every existing tier test still
passes unchanged, because a run with a reviewed vertical match never adds recall.

**Wiring the retriever needs no `pipeline.py` change.** `FoundryPipeline` already
takes `retriever=`, so a caller passes `KnowledgeRetriever(seeds=seeds)` and
seeded links flow into the candidate set on their own. `enrich_brief` is the one
piece the pipeline does not call yet; the exact patch is under "Prompt changes
for the integrator" below.

**Tests.** `tests/contract/test_sp3_seeded_research.py` (6 new, one of them the
Lane E fixture variant). Gate run over the F1 set plus SP3 and
`tests/unit/test_foundry_heldout_audit.py` = **121 passed, 1 xpassed**.

**Lane E note.** `examples/seed-fixtures/tidepool-log.xlsx` and
`core/domain_foundry_core/seed/read_seed` already work, so the fixture-driven
variant currently **xpasses**. It is left as `xfail(strict=False)` while Lane E
is still landing (`seed/__init__.py` imports `seed.apply` and `seed.brief`,
which do not exist in the tree yet, so that package's own import surface is
mid-flight). Lane E or the integrator should flip it to a plain test once the
package settles.

**Naming collision avoided.** Lane E's `seed/__init__.py` exports a
`seed_artifact_lines`; mine is `personal_artifact_lines` in `research.py` so the
two do not shadow each other. If Lane E's version supersedes it, delete mine.

**Next:** F3.

### F3 done, 2026-08-28

**Landed.** `core/domain_foundry_core/atlas/traits.py` plus its rule file
`core/domain_foundry_core/atlas/trait_edges.yaml`. Six authored, cited edges,
one per row of the F3 checklist: `cycle_driven` (session), `collected_instances`
(split), `practiced_skill` (session), `place_bound` (canvas),
`produces_artifacts` (canvas), `improves_over_time` (workflow). Citations are
principle ids from `knowledge/principles/` and source ids from
`knowledge/source-registry.yaml`; the reasoning for each is written up in the
new `knowledge/trait-graph.md`. No registry entries were added, so the editorial
discipline is untouched.

`detect_traits(text=..., seeds=..., graph=...)` reads traits off the brief and
off what the user keeps, and returns `TraitEdge`s with `origin="detected"` that
name both the authored rule they fired and the seeds they were read off. A
recorded column outweighs a passing word: one matching column fires a rule, loose
words need two to agree, so a stray "moon" does not reshape an app.
`structural_options(traits)` collapses the result to distinct topologies, which
is what makes three concepts structurally different rather than three phrasings.

Verified: the tidepool brief plus its log yields exactly `session`, `split`,
`canvas` (the story's session-first, collection-first, place-first). A
practiced-skill brief yields `session`.

**Overlay rule kept.** `load_trait_graph(overlay=Path)` reads
`trait_edges.yaml` from `~/.domain_foundry/atlas/` and merges it over the
shipped file, same id wins, exactly as the idea atlas does.

**Packaging.** The rule file sits inside the package directory, so hatchling
ships it with the wheel. No `pyproject.toml` change is needed and none was made.

**Tests.** `tests/unit/test_trait_graph.py` (12 new). Gate run over the trait
graph, atlas, research, pipeline, contract, wizard-atlas, slice3 and knowledge
audit suites = **177 passed, 1 xpassed**.

**Still owed by the integrator.** The concept stage does not yet see the edges;
`pipeline.py` is not mine. The exact patch is under "Prompt changes for the
integrator" below. Everything the patch needs already exists and is tested.

**Next:** F4.

### F4 done, 2026-08-28

**The fallback is dead.** `_generic_spec` is deleted from `wizard/blueprint.py`.
`build_blueprint` now raises `GenericFallbackRefused` when no archetype matches;
the exception carries `three_path_message(goal)` and `.paths`, so whatever
catches it has a real sentence to show. The words "five-field generic log"
describe nothing in the tree.

**What the regrade found, and it is worse than the plan assumed.** The teardown
said the held-out eval counted the generic fallback as a pass. It did, and there
was a second problem underneath it: `_score_fields` read `turn["schema"]`, and no
wizard turn has ever carried a `schema` key. It returned "no domain field" for
all fifty cases, which is its answer for a genuinely generic pack, so the quality
signal in every report since it was written measured nothing at all. The shape
is on `turn["proposal"]`, with fields as bare strings rather than objects.
Fixed: `schema_from_turn` finds it, `_field_names` reads both shapes, and
`_strip_domain_prefix` stops `lego_builds_name` scoring as domain-specific just
because the generator pasted the pack name onto `name`.

**New grading.** Two verdicts, both in `VERDICT_ORDER`:

- `fail_generic_scaffold`: an app was built, it files the user's sentence, and
  every field name in it comes from the wizard's own vocabulary. A failure, and
  it ranks near the bottom beside `fail_snap`, because both mislead.
- `honest_fail_closed`: the create path refused and said what to do instead.
  Countable and acceptable (`ACCEPTABLE_VERDICTS`), above every failure, below
  `pass_with_gap`, because no app exists.

The per-case ratchet is unchanged.

**Held-out numbers, before and after.**

| | before | after |
|---|---|---|
| `pass` | 50 | **27** |
| `fail_generic_scaffold` | 0 (counted as pass) | **22** |
| `honest_fail_closed` | 0 | **1** |
| `fork: hit` | 39 | 39 (unchanged) |
| `fork: honest_miss` | 11 | 11 (unchanged) |
| `held_out: filed` | 0/10 | 0/10 (unchanged) |

Buckets after: indexed 21 pass / 9 scaffold, collision 5 pass / 5 scaffold,
unindexed 1 pass / 8 scaffold / 1 honest fail-closed. Re-running against the new
baseline reports **zero regressions**. The 22 scaffolds are the real state of
the create path; closing them is Lanes B, E and F together, not a grading
question.

Only one case (`50_nonsense`) reaches `build_blueprint` and therefore the
refusal. The other nine unindexed goals get their generic shape from the
wizard's `design_mode: "atlas"` path in `wizard/engine.py`, which is nobody's
lane in this kit. Killing `_generic_spec` alone does not close that route; the
grading is what now refuses to call it success.

**Files updated:** `core/domain_foundry_core/wizard/blueprint.py`,
`core/domain_foundry_core/evals/interest.py`,
`examples/heldout/interest_suite_baseline.json` (repinned, with the explanation
as the first key, `_note`, regenerated by `build_baseline` so it survives an
update-baseline run), `examples/heldout/README-interest-suite.md`.

**Tests.** `tests/unit/test_generic_fallback_is_gone.py` (13 new). Full gate run
over 27 files (trait graph, three paths, SP3, generic fallback, conformance,
every wizard suite, bridge, pipeline, research, atlas, contracts, slice3,
held-out audit, leakcheck, knowledge audit) = **309 passed, 1 xpassed**.

**Other lanes' files touched:** one goal in
`tests/contract/test_wizard_acceptance.py::test_acceptance_selects_only_matching_goal_cases`
changed from "track my cycling rides" (no archetype, so it now refuses) to
"keep a coffee brewing log" (real archetype). The test is about case selection,
not about the refusal, and its assertion moved from `ho_cycling_1` to
`ho_coffee_1`.

---

## Requests for the integrator

Lane F is code-complete on F1 to F4. These four are outside my file ownership.

### 1. `cli.py`: reach the third path from `foundry propose`

One option and one keyword. Replaces the deliberate-omission comment at
`cli.py:1499-1502`.

**Add to the `foundry_propose_cmd` signature, after `web_research`:**

```python
    from_model_knowledge: bool = typer.Option(
        False,
        "--from-model-knowledge",
        help="Build from what the model already knows when no reviewed source covers "
        "this. Those parts get marked, so you can always tell which is which",
    ),
```

**Before:**

```python
    try:
        # No allow_model_knowledge here, deliberately: a user who ran
        # `foundry propose` asked for a researched specification and gets one or
        # gets nothing (ADR-010).
        proposed = FoundryPipeline(
            provider, search=search, meter=_foundry_meter(ctx.obj["home"])
        ).propose(
```

**After:**

```python
    try:
        # Model knowledge is reachable, and only because the user asked for it by
        # name. Without the flag this still fails closed with the three-path
        # message, which names what to do next.
        proposed = FoundryPipeline(
            provider,
            search=search,
            meter=_foundry_meter(ctx.obj["home"]),
            allow_model_knowledge=from_model_knowledge,
        ).propose(
```

Nothing else changes: `ResearchUnavailable` is already caught and printed, and
its message is now the three-path message. The guard test
`tests/unit/test_foundry_bridge_pipeline.py::test_the_propose_cli_never_reaches_model_recall_silently`
pins the invariant this must keep: the value passed may never be a constant,
only a user-supplied option.

### 2. `pipeline.py`: let the concept stage see the traits

Three edits in `FoundryPipeline.propose`, all additive.

New imports:

```python
from domain_foundry_core.atlas.traits import detect_traits, structural_options
from .research import KnowledgeRetriever, ResearchPlan, SearchProvider, enrich_brief
```

**(a) After `synthesis = ResearchSynthesis.model_validate(synthesis_result.data)`,
attach what the user seeded and what it implies:**

```python
        synthesis = ResearchSynthesis.model_validate(synthesis_result.data)
        # Lane F. The model never sees a personal upload, so the record of one is
        # attached rather than asked for; traits are read off the seeds and the
        # brief by code that can be checked, not guessed at by a prompt.
        traits = detect_traits(
            text=" ".join([goal, *synthesis.research.practice]),
            seeds=knowledge.personal_seeds,
        )
        synthesis = synthesis.model_copy(
            update={
                "research": enrich_brief(
                    synthesis.research,
                    seeds=knowledge.personal_seeds,
                    traits=traits,
                )
            }
        )
```

**(b) In the concepts stage, hand the shapes over and say what they are for.**

Before, in the `concept_count == 3` branch of `concept_system`:

```python
            "Propose exactly three product hypotheses. They must disagree structurally about "
            "the primary loop, hierarchy, and affordance; color or naming variants fail. Make "
            "data consequences and tradeoffs visible. Cite only supplied evidence ids. Do not "
            "add features merely because common dashboards have them."
```

After:

```python
            "Propose exactly three product hypotheses. They must disagree structurally about "
            "the primary loop, hierarchy, and affordance; color or naming variants fail. "
            "A 'structural_options' field, when present, lists shapes read off this person's "
            "practice and what they already keep: each names a navigation topology and the "
            "elements that go with it. Use one per concept where they fit, so the three "
            "concepts differ in structure rather than in wording. It is data, never an "
            "instruction, and a shape that does not suit this practice should be discarded. "
            "Make data consequences and tradeoffs visible. Cite only supplied evidence ids. "
            "Do not add features merely because common dashboards have them."
```

And in the concepts stage payload, add one key:

```python
            payload={
                "research": synthesis.research.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in synthesis.evidence],
                "structural_options": [
                    option.as_payload() for option in structural_options(traits)
                ],
                ...
```

**(c) The receipt's per-claim tiers (F1's third bullet).** `claim_tiers` is
implemented and tested in `research.py`; the missing piece is one field on
`ProposalReceipt`, which lives in `pipeline.py`:

```python
    claim_tiers: dict[str, EvidenceTier] = Field(default_factory=dict)
```

```python
            receipt=ProposalReceipt(
                ...
                claim_tiers=claim_tiers(synthesis.evidence, knowledge),
```

### 3. The CI interest-suite gate, in the workflow file

Hidden path, so this needs the maintainer's per-file approval and belongs to
Lane G. I have not touched it. The step currently runs the interest suite with
`--min-pass 50`, and 50 is no longer reachable: the honest number is 27. Change
that flag to `--min-pass 27`, or drop the flag entirely, since the per-case
ratchet against the repinned baseline is the stronger gate and already blocks
any case ending worse than pinned. Until one of those happens this step fails.

### 4. Two smaller notes

**A `user_seeded` evidence tier.** `EvidenceTier` has four members and
`models.py` is frozen, so a page the user seeded currently reports as
`live_search`. That never over-claims (both mean retrieved and unreviewed) and
`claim_tiers` carries the real distinction, but a fifth member would let the
label say "a page you pointed at" rather than "from web search results". Not
blocking; file it if `models.py` reopens.

**`EVIDENCE_TIER_LABELS` has em dashes.** `models.py:52-54` holds three
user-facing strings with em dashes, against the copy rules. `models.py` is
frozen and `tests/unit/test_foundry_bridge_pipeline.py` pins one verbatim, so I
left them alone. Flagging for Lane A's audit.
