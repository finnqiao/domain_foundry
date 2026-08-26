"""ADR-010: the wizard escalates into the Foundry pipeline, or says why it didn't.

`tests/contract/test_bridge_acceptance.py` already proves the second half of the
claim — given a researched spec, the projection produces a pack that files the
user's sentence. What was missing was the first half: nothing ever *called* the
pipeline, so `foundry/` was reachable only from the CLI and the Studio HTTP
surface, neither of which the hobbyist in `PRODUCT.md` will ever touch.

Everything here runs against a stub provider. There are no live keys in this
environment and none are needed: the stub replays a hand-authored showcase spec
through the real six-stage pipeline, so the pipeline, the projection, the
compiler, the dry-run gate, the router, and the receipt writer are all the real
thing. The one labelled part is the model's own judgement.

The two facts these tests exist to pin:

* a keyed create on an unindexed goal goes through research and the resulting
  pack files the sentence the user gave during elicitation, and
* a keyless or heuristic create does not escalate at all, which is what keeps
  `examples/heldout/interest_suite_baseline.json` at 50/50.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from domain_foundry_core.foundry.loader import load_foundry_spec
from domain_foundry_core.foundry.models import FoundrySpec
from domain_foundry_core.llm.provider import CompletionResult, LLMProvider, TokenUsage
from domain_foundry_core.wizard.escalation import ACCEPTANCE_EXPECTED

REPO_ROOT = Path(__file__).resolve().parents[2]

GOAL = "track my lego builds"
# The sentence `examples/showcase/lego-builds/README` promises the finished app
# will file. It is what the user types at the first elicitation prompt.
SEED = "finished the Millennium Falcon MOC, 3800 pieces, missing 2 tiles"
# The second sentence: held out of the shortlist, the examples and the rules,
# then replayed through the real router after activation.
HELD_OUT = "opened bag 4 of the Saturn V tonight, 40 minutes at the table"


def _showcase() -> FoundrySpec:
    return load_foundry_spec(REPO_ROOT / "examples" / "showcase" / "lego-builds" / "spec.yaml")


class StubFoundryProvider(LLMProvider):
    """A reasoning model that replays a hand-authored spec, stage by stage.

    It dispatches on the schema title the pipeline asks for, so the pipeline's
    own ordering, validation and reference-closure checks all run for real. The
    evidence stage remaps the spec's citations onto whatever the retriever
    actually returned, which is what lets the same stub serve both the
    ``reviewed_corpus`` and the ``model_knowledge`` paths.
    """

    name = "stub-foundry"

    def __init__(
        self,
        spec: FoundrySpec,
        *,
        unresearched: bool = False,
        fail_stage: str | None = None,
    ) -> None:
        self.spec = spec
        # ``unresearched`` plans an interest the reviewed corpus has never heard
        # of, which is the only way to reach the ``model_knowledge`` tier.
        self.unresearched = unresearched
        self.fail_stage = fail_stage
        self.stages: list[str] = []
        self.plan_payloads: list[dict[str, Any]] = []

    def has_live_keys(self) -> bool:
        return True

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        tier: str | None = None,
    ) -> CompletionResult:
        title = str((schema or {}).get("title") or "")
        payload = json.loads(user) if user.startswith("{") else {}
        if title:
            self.stages.append(title)
        if self.fail_stage and title == self.fail_stage:
            raise RuntimeError("stub provider refused this stage")
        return CompletionResult(
            data=self._data(title, payload),
            usage=TokenUsage(
                input_tokens=1_000,
                output_tokens=500,
                model="claude-opus-5",
                tier=tier,
                provider=self.name,
            ),
        )

    def _data(self, title: str, payload: dict[str, Any]) -> dict[str, Any]:
        spec = self.spec
        if title == "ResearchPlan":
            self.plan_payloads.append(payload)
            if self.unresearched:
                return {
                    "interest": "competitive cloud sculpting",
                    "desired_outcome": "Improve repeatable cloud sculptures",
                    "practice_hypotheses": ["Shape clouds by hand", "Compare sculpture outcomes"],
                    "queries": [
                        "cloud sculpting standard",
                        "cloud sculpting software",
                        "cloud sculpting schema",
                    ],
                    "vertical_keywords": ["cloud", "sculpting"],
                    "artifact_questions": ["What do you record?"],
                    "constraints": [],
                }
            return {
                "interest": spec.research.interest[:1_200],
                "desired_outcome": spec.research.desired_outcome[:1_200],
                "practice_hypotheses": [item[:1_200] for item in spec.research.practice[:3]],
                "queries": [
                    "lego moc data model",
                    "lego set inventory open source",
                    "lego build tracking applications",
                ],
                "vertical_keywords": ["lego", "moc", "brick", "set"],
                "artifact_questions": ["What do you already keep about your builds?"],
                "constraints": [item[:1_200] for item in spec.research.constraints][:20],
            }
        if title == "ResearchSynthesis":
            source_ids, evidence = self._cited(payload)
            return {
                "title": spec.title,
                "research": spec.research.model_dump(mode="json"),
                "source_ids": source_ids,
                "principle_ids": list(spec.principle_ids),
                "evidence": evidence,
            }
        if title == "SoleConcept":
            return {"concepts": [spec.concepts[0].model_dump(mode="json")]}
        if title == "ConceptSet":
            return {"concepts": [item.model_dump(mode="json") for item in spec.concepts]}
        if title == "DomainStage":
            return {"domain": spec.domain.model_dump(mode="json")}
        if title == "ExperienceStage":
            return {"experience": spec.experience.model_dump(mode="json")}
        if title == "DeliveryStage":
            return {
                "implementation": spec.implementation.model_dump(mode="json"),
                "derivations": [item.model_dump(mode="json") for item in spec.derivations],
            }
        # The wizard's look designer, which shares the same provider.
        return {"html": "<!doctype html><html><body><div>look</div></body></html>"}

    def _cited(self, payload: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
        """Cite only sources the retriever actually offered, as the pipeline demands."""
        offered = [str(item.get("id")) for item in payload.get("candidates") or []]
        kept = [item for item in self.spec.source_ids if item in offered]
        for candidate in offered:
            if len(kept) >= 3:
                break
            if candidate not in kept:
                kept.append(candidate)
        substitute = kept[0]
        evidence = []
        for item in self.spec.evidence:
            record = item.model_dump(mode="json")
            if record["source_id"] not in kept:
                record["source_id"] = substitute
            evidence.append(record)
        return kept, evidence


def _keyed(monkeypatch: pytest.MonkeyPatch, provider: LLMProvider) -> None:
    """Give the wizard a reasoning model without giving it a key."""
    from domain_foundry_core.wizard.engine import WizardEngine

    monkeypatch.delenv("DOMAIN_FOUNDRY_LLM", raising=False)
    monkeypatch.setattr(WizardEngine, "_tiered_provider", lambda self: provider)


def _create(api, goal: str, samples: list[str]) -> tuple[str, dict[str, Any]]:
    """Walk fork → looks → elicitation the way a person does."""
    turn = api.new_domain(goal)
    sid = str(turn["session_id"])
    if turn.get("state") == "fork":
        turn = api.wizard_reply(sid, "1")
    if turn.get("state") == "fork":
        turn = api.wizard_reply(sid, "yes")
    if turn.get("state") == "looks":
        turn = api.wizard_reply(sid, "build it")
    pending = list(samples)
    guard = 0
    while turn.get("state") == "elicit" and guard < 4:
        guard += 1
        turn = api.wizard_reply(sid, pending.pop(0) if pending else "skip")
    return sid, turn


def _harness(workspace):
    from domain_foundry_core.api.harness import HarnessAPI

    api = HarnessAPI(workspace.home)
    api.init()
    return api


def _filed(receipt, pack: str) -> list:
    return [
        span
        for span in receipt.routed
        if span.domain == pack and span.disposition not in {"unfiled", "ledger_only"}
    ]


# --------------------------------------------------------------------------- #
# The escalation
# --------------------------------------------------------------------------- #


def test_a_keyed_create_on_an_unindexed_goal_builds_from_a_researched_spec(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])

    assert turn["state"] == "test_drive", turn.get("message")
    assert turn.get("bridge"), "the create did not escalate into the Foundry pipeline"
    assert turn["bridge"]["evidence_tier"] == "reviewed_corpus"
    # All six stages ran, in the pipeline's own order, asking for one concept.
    assert [name for name in provider.stages if name.endswith(("Plan", "Synthesis", "Stage", "Concept"))] == [
        "ResearchPlan",
        "ResearchSynthesis",
        "SoleConcept",
        "DomainStage",
        "ExperienceStage",
        "DeliveryStage",
    ]
    assert turn["design_mode"] == "llm"
    assert not turn.get("bridge_fallback_reason")


def test_an_indexed_but_thin_neighbourhood_also_escalates_and_elicits(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trigger is not just "unindexed".

    `diving.scuba.dive_log` forks correctly and still lends no vocabulary and no
    analog pack, which is the shape of the sixteen audit rows that forked right
    and then could not file the user's first sentence. It elicits — through the
    existing state machine, not a second one — and then escalates.
    """
    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    turn = api.new_domain("log my scuba dives")
    sid = str(turn["session_id"])
    turn = api.wizard_reply(sid, "1")
    if turn.get("state") == "looks":
        turn = api.wizard_reply(sid, "build it")

    assert turn["state"] == "elicit", turn.get("message")
    turn = api.wizard_reply(sid, SEED)
    turn = api.wizard_reply(sid, HELD_OUT)

    assert turn["state"] == "test_drive", turn.get("message")
    assert turn.get("bridge"), "an indexed neighbourhood with no words should escalate"


def test_the_bridged_pack_files_the_sentence_the_user_gave(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point. A keyword scaffold cannot file this sentence; research can."""
    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])
    pack = str(turn["pack"]["name"])

    filed = _filed(api.capture(SEED), pack)
    assert filed, f"{SEED!r} did not file into the researched pack {pack!r}"

    # Richer vocabulary is exactly how a router starts over-capturing.
    assert not _filed(api.capture("nice afternoon, weather was good"), pack)


def test_the_held_out_sentence_is_replayed_and_never_enters_the_design(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])

    assert turn["held_out"]["text"] == HELD_OUT
    # The design never saw this sentence, so where it lands is a measurement.
    assert turn["held_out"]["filed"] is True, turn["held_out"]
    pack_root = Path(turn["pack"]["path"])
    routing = (pack_root / "routing.yaml").read_text(encoding="utf-8")
    assert SEED in routing, "the first sentence should be a routing example"
    assert HELD_OUT not in routing, "the held-out sentence must not reach the pack"


def test_both_elicited_sentences_become_the_runs_acceptance_tasks(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-010: the user authors both inputs, so the generator never judges itself."""
    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])
    receipts = json.loads(
        (Path(turn["pack"]["path"]) / "foundry" / "receipts.json").read_text(encoding="utf-8")
    )

    assert [item["input"] for item in receipts["acceptance_tasks"]] == [SEED, HELD_OUT]
    assert {item["expected"] for item in receipts["acceptance_tasks"]} == {ACCEPTANCE_EXPECTED}


def test_the_atlas_is_passed_as_a_prior_not_as_the_answer(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    _create(api, GOAL, [SEED, HELD_OUT])

    prior = provider.plan_payloads[0]["prior"]
    assert prior["catalogue_had_no_match"] is True
    assert prior["idea_cards"], "the offered idea cards should seed research"
    assert prior["user_sentences"] == [SEED, HELD_OUT]
    assert "discard" in prior["note"].lower()


# --------------------------------------------------------------------------- #
# The evidence tier, and where it is stamped
# --------------------------------------------------------------------------- #


def test_the_evidence_tier_reaches_the_pack_metadata(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])
    status = json.loads(
        (Path(turn["pack"]["path"]) / "foundry_status.json").read_text(encoding="utf-8")
    )

    assert status["mode"] == "reviewed_corpus"
    assert status["evidence_label"] == "from reviewed sources"
    assert status["bridge_fallback_reason"] is None


def test_model_recall_is_stamped_as_model_recall_and_never_as_research(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unindexed hobby with no reviewed evidence still gets a pack — and a label."""
    provider = StubFoundryProvider(_showcase(), unresearched=True)
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])
    status = json.loads(
        (Path(turn["pack"]["path"]) / "foundry_status.json").read_text(encoding="utf-8")
    )

    assert status["mode"] == "model_knowledge"
    assert status["evidence_label"] == "from the model's own knowledge — not verified sources"
    assert "not verified sources" in turn["message"]


def test_a_keyless_pack_is_stamped_fallback_demo_and_says_so(workspace) -> None:
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])
    status = json.loads(
        (Path(turn["pack"]["path"]) / "foundry_status.json").read_text(encoding="utf-8")
    )

    assert status["mode"] == "fallback_demo"
    assert status["evidence_label"] == "built from your own words — no research was run"
    assert "No reasoning model is configured" in turn["message"]
    assert "add a key later" in turn["message"]


# --------------------------------------------------------------------------- #
# Persisted receipts
# --------------------------------------------------------------------------- #


def test_every_step_of_the_run_is_openable_under_the_pack(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])
    root = Path(turn["pack"]["path"]) / "foundry"

    assert sorted(item.name for item in root.iterdir()) == [
        "README.md",
        "evidence.json",
        "proposal.yaml",
        "receipts.json",
        "shortlist.json",
        "spec.yaml",
    ]
    # The persisted spec is the real thing, not a summary of it.
    persisted = load_foundry_spec(root / "spec.yaml")
    assert persisted.evidence_tier == "reviewed_corpus"
    assert len(persisted.concepts) == 1
    assert "wizard-auto: sole concept" in persisted.remix.user_decisions

    receipts = json.loads((root / "receipts.json").read_text(encoding="utf-8"))
    assert [item["stage"] for item in receipts["stages"]] == [
        "research_plan",
        "evidence",
        "concepts",
        "domain",
        "experience",
        "delivery",
    ]
    assert all(item["model"] == "claude-opus-5" for item in receipts["stages"])


def test_the_bridged_run_is_billed_to_the_foundry_tier(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Six sota calls used to be invisible to the guard that exists to bound them."""
    import sqlite3

    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    _create(api, GOAL, [SEED, HELD_OUT])

    conn = sqlite3.connect(workspace.ledger_db)
    rows = conn.execute("SELECT tier, entry_id FROM cost_ledger WHERE tier = 'foundry'").fetchall()
    conn.close()
    assert len(rows) == 6
    assert all(entry.startswith("foundry:wz_") for _tier, entry in rows)


# --------------------------------------------------------------------------- #
# Honest failure
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("fail_stage", "fragment"),
    [
        ("ResearchPlan", "research_plan stage failed validation"),
        ("ResearchSynthesis", "evidence stage failed validation"),
        ("SoleConcept", "concepts stage failed validation"),
        ("DomainStage", "domain stage failed validation"),
    ],
)
def test_a_provider_error_at_any_stage_falls_back_and_names_itself(
    workspace, monkeypatch: pytest.MonkeyPatch, fail_stage: str, fragment: str
) -> None:
    provider = StubFoundryProvider(_showcase(), fail_stage=fail_stage)
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])

    assert turn["state"] == "test_drive", turn.get("message")
    assert turn.get("pack"), "a failed research run must still leave a working pack"
    assert fragment in turn["bridge_fallback_reason"]
    assert "couldn't" in turn["message"]
    assert "built from your own words" in turn["message"]
    status = json.loads(
        (Path(turn["pack"]["path"]) / "foundry_status.json").read_text(encoding="utf-8")
    )
    assert status["mode"] == "fallback_demo"
    assert fragment in status["bridge_fallback_reason"]


def test_an_exhausted_budget_falls_back_before_it_spends_anything(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    monkeypatch.setenv("DOMAIN_FOUNDRY_DAILY_COST_CAP", "0")
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])

    assert turn["state"] == "test_drive", turn.get("message")
    assert "daily cost cap" in turn["bridge_fallback_reason"]
    assert not any(name.startswith("Research") for name in provider.stages)


def test_a_cap_reached_mid_run_stops_cleanly_and_says_which_stage(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from domain_foundry_core.wizard import engine as engine_module

    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)

    class ThreeCallMeter:
        spent_usd = 0.0

        def __init__(self) -> None:
            self.budget = 3

        def allow(self) -> bool:
            return self.budget > 0

        def record(self, **_: Any) -> None:
            self.budget -= 1

    monkeypatch.setattr(
        engine_module.WizardEngine, "_foundry_meter", lambda self, session: ThreeCallMeter()
    )
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])

    assert turn["state"] == "test_drive", turn.get("message")
    assert "cost cap was reached before the domain stage" in turn["bridge_fallback_reason"]


def test_a_spec_that_will_not_project_falls_back_rather_than_installing_nothing(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from domain_foundry_core.wizard import escalation

    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)

    def _explode(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("no entity could carry a sentence")

    monkeypatch.setattr(escalation, "spec_to_shortlist", _explode)
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])

    assert turn["state"] == "test_drive", turn.get("message")
    assert "would not project onto a pack" in turn["bridge_fallback_reason"]
    assert turn["pack"]["name"]


def test_a_bridged_pack_that_misses_the_dry_run_gate_falls_back(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bridged pack routes its own examples like any other, or it does not ship."""
    from domain_foundry_core.wizard.engine import WizardEngine

    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)

    real_dry_run = WizardEngine._dry_run
    state = {"missed": False}

    def once_bad(self: Any, draft_dir: Path) -> dict[str, Any]:
        report = real_dry_run(self, draft_dir)
        if not state["missed"]:
            state["missed"] = True
            return {**report, "accuracy": 0.0, "routed": 0, "failures": []}
        return report

    monkeypatch.setattr(WizardEngine, "_dry_run", once_bad)
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])

    assert turn["state"] == "test_drive", turn.get("message")
    assert turn["pack"]["name"], "the fallback must still leave a working pack"
    assert "did not clear the dry-run gate" in turn["bridge_fallback_reason"]
    assert not turn.get("bridge")


def test_skipping_elicitation_does_not_escalate_and_says_why(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bridge cannot judge itself, so with no user sentences it does not run."""
    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [])

    assert turn["state"] == "test_drive", turn.get("message")
    assert not turn.get("bridge")
    assert "skipped the sentences" in turn["bridge_fallback_reason"]
    assert not any(name.startswith("Research") for name in provider.stages)


# --------------------------------------------------------------------------- #
# The offline path stays offline
# --------------------------------------------------------------------------- #


def test_a_keyless_create_never_touches_the_pipeline(workspace) -> None:
    """This is the property the 50/50 interest suite is pinned on."""
    from domain_foundry_core.wizard.engine import WizardEngine

    api = _harness(workspace)
    engine = WizardEngine(api)

    assert engine._bridge_provider() is None

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])
    assert turn["state"] == "test_drive", turn.get("message")
    assert not turn.get("bridge")
    # Absence of a key is not a failure and must not be reported as one.
    assert not turn.get("bridge_fallback_reason")


def test_an_explicitly_heuristic_install_does_not_escalate_even_with_a_key(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "heuristic")
    api = _harness(workspace)

    _sid, turn = _create(api, GOAL, [SEED, HELD_OUT])

    assert turn["state"] == "test_drive", turn.get("message")
    assert not turn.get("bridge")
    # The wizard's own blueprint designer is unchanged by this — only the
    # pipeline, which is the expensive path, honours the switch.
    assert not any(name.startswith("Research") for name in provider.stages)


@pytest.mark.parametrize(
    "goal",
    [
        # `sports.strength.session_log` carries 18 atlas vocabulary terms.
        "log my gym lifting program",
        # `plants.houseplants.care_log` has a bundled analog pack to copy.
        "track my houseplants",
    ],
)
def test_an_atlas_neighbourhood_that_can_furnish_the_goal_is_left_alone(
    workspace, monkeypatch: pytest.MonkeyPatch, goal: str
) -> None:
    """The atlas is demoted where it was never much of an answer, not everywhere.

    No ``bridge_fallback_reason`` is the load-bearing assertion: it says the
    bridge was never eligible, rather than eligible and quietly declined.
    """
    provider = StubFoundryProvider(_showcase())
    _keyed(monkeypatch, provider)
    api = _harness(workspace)

    _sid, turn = _create(api, goal, [])

    assert turn["state"] == "test_drive", turn.get("message")
    assert not turn.get("bridge")
    assert not turn.get("bridge_fallback_reason")
    assert not any(name.startswith("Research") for name in provider.stages)
