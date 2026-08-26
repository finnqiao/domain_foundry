# ADR-010: The wizard escalates into the Foundry pipeline

- Status: accepted
- Date: 2026-08-23

## Context

Two creation paths exist and only one is reachable.

`core/domain_foundry_core/foundry/` (ADR-008, ADR-009) researches an interest
against a reviewed corpus, produces three structurally distinct concepts, derives
a workload-fit domain model and an experience contract, and compiles a preview
and an owned app from one spec, with receipts. It is the product described in
`PRODUCT.md`.

`core/domain_foundry_core/wizard/` matches a goal against a 100-node atlas and
compiles a pack from job templates. It is what `new-domain`, the web `/create`
route, MCP, Telegram, and hermes-agent all drive. There are no imports between
the two packages.

The 50-interest audit measured the reachable path at 28/50. Its failures are not
polish: six goals landed in a confidently wrong neighbourhood, and sixteen more
forked correctly and then could not file the user's first sentence.

The Foundry path is unreachable for the person `PRODUCT.md` names as the primary
user, because it demands three things they cannot supply: a configured reasoning
model, a matching reviewed vertical source or a Brave key, and **two
hand-authored acceptance tasks in `action => observable outcome` form**. The last
is a research-methods exercise, not a question a hobbyist answers.

## Decision

### The wizard escalates rather than duplicating

`wizard/bridge.py` calls the Foundry pipeline. The import is one-directional:
`wizard` may import `foundry`; `foundry` must never import `wizard`. The
pipeline stays usable on its own, and no third creation path is introduced.

When a reasoning model is configured, a create runs through the bridge. The atlas
is demoted from terminal authority to a **prior**: its neighbourhood, idea cards,
world analogs, and jargon seed the research stage instead of deciding the answer.
Without a key the wizard's own path runs, labelled as a fallback demo.

### Two elicited sentences are the acceptance evidence

The wizard asks for two things the user would actually log, in their own words.

- The **first** shapes the design: its tokens become vocabulary, it becomes a
  routing example, its nouns seed identity values.
- The **second is held out**. It never enters the shortlist, the examples, or the
  compiled rules. After activation it is replayed through the real router and the
  result is reported honestly.

Both become `AcceptanceTask`s: `input` is the user's sentence verbatim, `expected`
is a mechanical template ("files into the app and appears in its main view").

This satisfies the rule behind `cli.py`'s two-task requirement — the generator
cannot author its own judge — because both inputs are user-authored. It changes
only the interface for collecting them. A conversational prompt gets a real
sentence from a real hobbyist; a form asking for an observable outcome gets an
abandoned session.

### Evidence tiers are stamped, never implied

Every bridged pack and receipt records how its research was sourced:

| Tier | Meaning |
|---|---|
| `reviewed_corpus` | A `domain_exemplar` source in the reviewed registry matched |
| `live_search` | Brave discovery, already `reference_only` |
| `model_knowledge` | **Bridge only.** The model's own recall, labelled *not verified sources* |
| `fallback_demo` | No reasoning model; built from the user's words alone |

`model_knowledge` is new and deliberately constrained. `foundry propose` keeps
its hard `ResearchUnavailable` gate: a user who explicitly asked for a researched
specification gets one or gets nothing. The bridge may fall to model recall
because the alternative for an unindexed hobby is the keyword scaffold, which is
strictly worse and says nothing about its own provenance. What makes it
acceptable is that it is named, in the receipt, in the pack metadata, and in the
copy the user reads.

### One concept, with the reason recorded

The pipeline's three-concept requirement exists so a user can choose between real
alternatives. Inside a conversational create there is no comparison surface, so
the bridge requests `concept_count=1` and records the remix decision as
`wizard-auto: sole concept`. The structural-distinctness validator is relaxed for
`n=1` only; the three-concept path in Foundry Studio is unchanged.

### The spec lands in the existing runtime

`spec_to_shortlist()` is a deterministic projection from `FoundrySpec` to the
wizard's `ShortlistModel`: entities become objects, attributes become fields with
roles, spec vocabulary becomes jargon, evaluation-adjacent examples become
routing examples. The result goes through the existing `compile_jobs` and the
existing dry-run gate, so a bridged pack must route its own examples like any
other. Capture, correction, provenance, and export keep working because nothing
about the runtime changed.

The full spec, evidence, and stage receipts persist under `<pack>/foundry/` so a
technical user can open every step.

### Bridged work is metered

The bridge and the `foundry` CLI commands write `routing/cost.py` ledger rows
under the tier label `foundry`, check the daily cap before starting, and stop
cleanly if the cap is reached mid-run, keeping the receipts already earned. The
foundry path previously recorded per-stage token receipts but wrote nothing to
the ledger, so its spend was invisible to the guard that exists to bound it.

## Consequences

The reachable create path becomes the researched one whenever a key is present,
and the `foundry/` package stops being dead weight. The non-technical user is
asked for two sentences instead of two acceptance criteria.

The cost is a real coupling: `wizard` now depends on `foundry`, and a pipeline
contract change can break a create. The one-directional rule and the
`spec_to_shortlist` seam keep that coupling to a single, testable projection.

`model_knowledge` widens what may be called research. The mitigation is labelling
rather than restriction, which is a judgement that the user is better served by
an honest weaker answer than by a silent generic one. If that judgement proves
wrong, the tier can be disabled without touching the bridge.

Offline behaviour is unchanged, which is why the interest suite keeps running in
heuristic mode as the gate on the fallback path.
