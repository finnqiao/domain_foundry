"""ADR-010's three pipeline-side changes: one concept, model recall, and metering.

Each is a relaxation of something that was previously absolute, so each test
here comes in a pair: the new path works, and the old guarantee is still a
guarantee. There are no live keys in this environment and none are needed —
every stage is a stub.
"""

from __future__ import annotations

import ast
import json
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from domain_foundry_core.foundry.compiler import FoundryCompiler
from domain_foundry_core.foundry.cost import FOUNDRY_COST_TIER, LedgerCostMeter
from domain_foundry_core.foundry.loader import load_golden_specs
from domain_foundry_core.foundry.models import (
    SOLE_CONCEPT_DECISION,
    FoundrySpec,
    SourceSnapshot,
    evidence_tier_label,
)
from domain_foundry_core.foundry.pipeline import (
    AcceptanceTask,
    BudgetExhausted,
    FoundryPipeline,
    PipelineError,
)
from domain_foundry_core.foundry.research import (
    KnowledgeRetriever,
    ResearchPlan,
    ResearchUnavailable,
    model_knowledge_candidates,
)
from domain_foundry_core.llm.provider import CompletionResult, LLMProvider, TokenUsage
from domain_foundry_core.routing.cost import CostGuard, CostGuardConfig


class SequenceProvider(LLMProvider):
    name = "sequence-test"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        tier: str | None = None,
    ) -> CompletionResult:
        self.calls.append({"system": system, "user": user, "schema": schema, "tier": tier})
        return CompletionResult(
            data=self.responses.popleft(),
            usage=TokenUsage(
                input_tokens=1_000,
                output_tokens=500,
                model="claude-opus-5",
                tier=tier,
                provider=self.name,
            ),
        )


class StubMeter:
    """A ledger stand-in. ``budget`` is how many calls it will still allow."""

    def __init__(self, budget: int = 99) -> None:
        self.budget = budget
        self.rows: list[dict[str, Any]] = []

    def allow(self) -> bool:
        return self.budget > 0

    def record(
        self,
        *,
        stage: str,
        provider: str | None,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self.budget -= 1
        self.rows.append(
            {
                "stage": stage,
                "provider": provider,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )


def _golden() -> FoundrySpec:
    return next(spec for spec in load_golden_specs() if spec.id == "sourdough-lab")


def _acceptance_tasks() -> list[AcceptanceTask]:
    return [
        AcceptanceTask(
            input="Record a real feeding and see whether the starter is ready.",
            expected="The feeding is linked to the starter and readiness is visible.",
        ),
        AcceptanceTask(
            input="Compare two bakes that used different fermentation choices.",
            expected="The app shows the input and outcome differences without losing either bake.",
        ),
    ]


def _plan_payload(golden: FoundrySpec) -> dict[str, Any]:
    return {
        "interest": "sourdough fermentation",
        "desired_outcome": golden.research.desired_outcome,
        "practice_hypotheses": golden.research.practice[:3],
        "queries": [
            "sourdough fermentation measurements open source",
            "sourdough starter data model",
            "sourdough baking workflow applications",
        ],
        "vertical_keywords": ["sourdough", "starter", "fermentation", "bake"],
        "artifact_questions": ["Do you already keep a bake notebook?"],
        "constraints": golden.research.constraints,
    }


def _sole_remix(golden: FoundrySpec, concept_id: str):  # type: ignore[no-untyped-def]
    """A remix for a one-concept proposal: nothing left to borrow fragments from."""
    return golden.remix.model_copy(update={"selected_concept": concept_id, "fragments": []})


def _responses(golden: FoundrySpec, *, concepts: int = 3) -> list[dict[str, Any]]:
    return [
        _plan_payload(golden),
        {
            "title": golden.title,
            "research": golden.research.model_dump(mode="json"),
            "source_ids": golden.source_ids,
            "principle_ids": golden.principle_ids,
            "evidence": [item.model_dump(mode="json") for item in golden.evidence],
        },
        {"concepts": [item.model_dump(mode="json") for item in golden.concepts[:concepts]]},
        {"domain": golden.domain.model_dump(mode="json")},
        {"experience": golden.experience.model_dump(mode="json")},
        {
            "implementation": golden.implementation.model_dump(mode="json"),
            "derivations": [item.model_dump(mode="json") for item in golden.derivations],
        },
    ]


# --------------------------------------------------------------------------- #
# One concept, with the reason recorded
# --------------------------------------------------------------------------- #


def test_single_concept_mode_produces_a_spec_that_records_why() -> None:
    golden = _golden()
    provider = SequenceProvider(_responses(golden, concepts=1))
    pipeline = FoundryPipeline(provider)

    proposed = pipeline.propose(
        "Help me improve my sourdough fermentation",
        acceptance_tasks=_acceptance_tasks(),
        concept_count=1,
    )
    assert len(proposed.proposal.concepts) == 1

    remix = _sole_remix(golden, proposed.proposal.concepts[0].id)
    spec = pipeline.complete(proposed.proposal, remix)

    assert len(spec.concepts) == 1
    assert SOLE_CONCEPT_DECISION in spec.remix.user_decisions
    # The user's own decisions are kept alongside the machine's.
    assert set(golden.remix.user_decisions) <= set(spec.remix.user_decisions)


def test_single_concept_stage_asks_for_one_and_does_not_demand_disagreement() -> None:
    """The distinctness validator is not merely relaxed at n=1; it cannot apply."""
    golden = _golden()
    provider = SequenceProvider(_responses(golden, concepts=1))

    FoundryPipeline(provider).propose(
        "Help me improve my sourdough fermentation",
        acceptance_tasks=_acceptance_tasks(),
        concept_count=1,
    )
    concept_call = provider.calls[2]
    assert "exactly one product hypothesis" in concept_call["system"]
    assert concept_call["schema"]["properties"]["concepts"]["maxItems"] == 1


def test_three_concept_studio_path_still_rejects_cosmetic_variants() -> None:
    """The relaxation must not have leaked into the path it was not for."""
    golden = _golden()
    responses = _responses(golden)
    for index, concept in enumerate(responses[2]["concepts"]):
        concept["primary_loop"] = "Record an item and inspect the same overview"
        concept["primary_affordance"] = "The same dashboard card"
        concept["workflow_ids"] = ["same_workflow"]
        concept["title"] = f"Color variant {index}"

    with pytest.raises(PipelineError, match="concepts stage failed validation"):
        FoundryPipeline(SequenceProvider(responses)).propose(
            "Help me improve my sourdough fermentation",
            acceptance_tasks=_acceptance_tasks(),
        )


def test_three_concept_path_still_refuses_a_short_concept_set() -> None:
    golden = _golden()
    responses = _responses(golden, concepts=1)

    with pytest.raises(PipelineError, match="concepts stage failed validation"):
        FoundryPipeline(SequenceProvider(responses)).propose(
            "Help me improve my sourdough fermentation",
            acceptance_tasks=_acceptance_tasks(),
        )


def test_a_concept_count_other_than_one_or_three_is_refused() -> None:
    with pytest.raises(PipelineError, match="concept_count"):
        FoundryPipeline(SequenceProvider([])).propose(
            "Help me improve my sourdough fermentation",
            acceptance_tasks=_acceptance_tasks(),
            concept_count=2,
        )


def test_a_one_concept_spec_without_the_recorded_reason_is_invalid() -> None:
    """The relaxation is conditional on saying so, so it can never be silent."""
    golden = _golden()
    payload = golden.model_dump(mode="json")
    payload["concepts"] = payload["concepts"][:1]
    payload["remix"]["selected_concept"] = payload["concepts"][0]["id"]
    payload["remix"]["fragments"] = []

    with pytest.raises(ValueError, match="wizard-auto: sole concept"):
        FoundrySpec.model_validate(payload)

    payload["remix"]["user_decisions"] = [
        *payload["remix"]["user_decisions"],
        SOLE_CONCEPT_DECISION,
    ]
    assert len(FoundrySpec.model_validate(payload).concepts) == 1


def test_two_concepts_are_never_a_valid_spec() -> None:
    golden = _golden()
    payload = golden.model_dump(mode="json")
    payload["concepts"] = payload["concepts"][:2]
    payload["remix"]["selected_concept"] = payload["concepts"][0]["id"]
    payload["remix"]["fragments"] = []
    payload["remix"]["user_decisions"] = [SOLE_CONCEPT_DECISION]

    with pytest.raises(ValueError, match="three comparable concepts, or one declared sole one"):
        FoundrySpec.model_validate(payload)


# --------------------------------------------------------------------------- #
# The model_knowledge evidence tier
# --------------------------------------------------------------------------- #


def _unresearched_plan() -> ResearchPlan:
    return ResearchPlan(
        interest="competitive cloud sculpting",
        desired_outcome="Improve repeatable cloud sculptures",
        practice_hypotheses=["Shape clouds by hand", "Compare sculpture outcomes"],
        queries=[
            "cloud sculpting standard",
            "cloud sculpting software",
            "cloud sculpting schema",
        ],
        vertical_keywords=["cloud", "sculpting"],
        artifact_questions=["What do you record?"],
    )


def test_retrieval_still_fails_closed_by_default() -> None:
    with pytest.raises(ResearchUnavailable, match="will not present a generic scaffold"):
        KnowledgeRetriever().retrieve(_unresearched_plan())


def test_model_knowledge_is_opt_in_and_labelled_at_every_layer() -> None:
    retrieved = KnowledgeRetriever().retrieve(_unresearched_plan(), allow_model_knowledge=True)

    assert retrieved.tier == "model_knowledge"
    assert retrieved.external
    for candidate in retrieved.external:
        source = candidate.source
        assert source.tier == "model_knowledge"
        assert source.status == "reference_only"
        assert source.origin == "model_recall"
        assert source.url is None
        assert source.id.startswith("model_recall_")
        assert "Unverified recall" in candidate.excerpt


def test_model_recall_cannot_be_dressed_up_as_a_retrieved_source() -> None:
    base = model_knowledge_candidates(_unresearched_plan())[0].source.model_dump(mode="json")

    with pytest.raises(ValueError, match="model recall has no URL"):
        SourceSnapshot.model_validate({**base, "url": "https://example.com/whatever"})
    with pytest.raises(ValueError, match="never approved"):
        SourceSnapshot.model_validate({**base, "status": "approved"})
    with pytest.raises(ValueError, match="requires tier=model_knowledge"):
        SourceSnapshot.model_validate(
            {**base, "tier": "domain_exemplar", "url": "https://example.com/x"}
        )


def test_a_retrieved_source_must_still_cite_its_url() -> None:
    """Making ``url`` optional for recall must not make it optional generally."""
    with pytest.raises(ValueError, match="must cite the URL"):
        SourceSnapshot.model_validate(
            {
                "id": "sneaky",
                "title": "No URL here",
                "publisher": "someone",
                "kind": "web_search_result",
                "tier": "product_reference",
                "license": "unknown-reference",
                "allowed_uses": ["reference_facts"],
                "status": "reference_only",
                "retrieved_at": "2026-08-23",
                "freshness_days": 90,
                "topics": ["research"],
            }
        )


def test_guaranteed_source_slate_is_untouched_by_the_recall_path() -> None:
    """ADR-009's cross-cutting slate is load-bearing and must still arrive."""
    plain = KnowledgeRetriever().retrieve(_unresearched_plan(), allow_model_knowledge=True)
    ids = {str(source.get("id")) for source in plain.registered}

    assert {"w3c_prov", "wcag_22", "owasp_llmsvs"} <= ids


def test_reviewed_corpus_and_live_search_tiers_are_still_reported() -> None:
    golden = _golden()
    plan = ResearchPlan.model_validate(_plan_payload(golden))

    retrieved = KnowledgeRetriever().retrieve(plan, allow_model_knowledge=True)
    assert retrieved.tier == "reviewed_corpus"


def test_the_tier_reaches_the_receipt_the_pack_and_the_copy() -> None:
    golden = _golden()
    provider = SequenceProvider(_responses(golden, concepts=1))
    pipeline = FoundryPipeline(provider, allow_model_knowledge=True)

    proposed = pipeline.propose(
        "Help me improve my sourdough fermentation",
        acceptance_tasks=_acceptance_tasks(),
        concept_count=1,
    )
    # This interest *does* match reviewed evidence, so the tier must say so
    # rather than claiming recall just because recall was permitted.
    assert proposed.proposal.receipt.evidence_tier == "reviewed_corpus"

    remix = _sole_remix(golden, proposed.proposal.concepts[0].id)
    spec = pipeline.complete(proposed.proposal, remix)
    assert spec.evidence_tier == "reviewed_corpus"
    assert spec.evidence_tier_label == "from reviewed sources"


def test_the_model_knowledge_label_is_the_sentence_the_user_reads() -> None:
    assert (
        evidence_tier_label("model_knowledge")
        == "from the model's own knowledge — not verified sources"
    )
    # An unstamped spec is never upgraded into a claim of research.
    assert evidence_tier_label(None) == "built from your own words — no research was run"


def test_an_unstamped_golden_reports_no_tier() -> None:
    assert _golden().evidence_tier is None


def test_the_tier_is_readable_from_the_compiled_bundle(tmp_path: Path) -> None:
    """Where the label actually reaches a user: the receipt and the README."""
    golden = _golden()
    payload = golden.model_dump(mode="json")
    payload["generation"] = {
        "origin": "model_assisted",
        "pipeline_version": "foundry-pipeline/1.0",
        "generated_at": "2026-08-23T00:00:00+00:00",
        "stages": [],
        "evidence_tier": "model_knowledge",
    }
    spec = FoundrySpec.model_validate(payload)

    artifact = FoundryCompiler().compile(spec, tmp_path / "bundle")
    receipt = json.loads(artifact.receipt.read_text(encoding="utf-8"))

    assert receipt["evidence_tier"] == "model_knowledge"
    assert receipt["evidence_label"] == "from the model's own knowledge — not verified sources"
    assert receipt["generation"]["evidence_tier"] == "model_knowledge"
    readme = (artifact.root / "README.md").read_text(encoding="utf-8")
    assert "not verified sources" in readme


def test_the_default_pipeline_still_fails_closed_on_an_unresearched_interest() -> None:
    provider = SequenceProvider([_unresearched_plan().model_dump(mode="json")])
    pipeline = FoundryPipeline(provider)

    assert pipeline.allow_model_knowledge is False
    with pytest.raises(ResearchUnavailable, match="will not present a generic scaffold"):
        pipeline.propose("Track competitive cloud sculpting", acceptance_tasks=_acceptance_tasks())


def test_the_propose_cli_never_opts_into_model_recall() -> None:
    """ADR-010: `foundry propose` keeps its hard gate.

    A user who explicitly asked for a researched specification gets one or gets
    nothing. If a future change wants to surface model recall on the command
    line it needs a deliberate decision and a rewrite of this test, not a
    keyword argument that slips in with something else.
    """
    path = Path(__file__).resolve().parents[2] / "core" / "domain_foundry_core" / "cli.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    passed = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg == "allow_model_knowledge"
    ]
    assert not passed, "the foundry CLI must not enable model recall"


# --------------------------------------------------------------------------- #
# Cost metering
# --------------------------------------------------------------------------- #


def test_every_sota_call_writes_one_metered_row() -> None:
    golden = _golden()
    meter = StubMeter()
    pipeline = FoundryPipeline(SequenceProvider(_responses(golden)), meter=meter)

    proposed = pipeline.propose(
        "Help me improve my sourdough fermentation",
        acceptance_tasks=_acceptance_tasks(),
    )
    pipeline.complete(proposed.proposal, golden.remix)

    assert [row["stage"] for row in meter.rows] == [
        "research_plan",
        "evidence",
        "concepts",
        "domain",
        "experience",
        "delivery",
    ]
    assert all(row["model"] == "claude-opus-5" for row in meter.rows)
    assert all(row["input_tokens"] == 1_000 for row in meter.rows)


def test_a_cap_already_reached_stops_the_run_before_it_spends_anything() -> None:
    provider = SequenceProvider(_responses(_golden()))
    meter = StubMeter(budget=0)

    with pytest.raises(BudgetExhausted) as caught:
        FoundryPipeline(provider, meter=meter).propose(
            "Help me improve my sourdough fermentation",
            acceptance_tasks=_acceptance_tasks(),
        )
    assert provider.calls == []
    assert caught.value.receipts == []


def test_a_cap_reached_mid_run_keeps_the_receipts_already_earned() -> None:
    provider = SequenceProvider(_responses(_golden()))
    meter = StubMeter(budget=2)

    with pytest.raises(BudgetExhausted) as caught:
        FoundryPipeline(provider, meter=meter).propose(
            "Help me improve my sourdough fermentation",
            acceptance_tasks=_acceptance_tasks(),
        )

    assert caught.value.stage == "concepts"
    assert [receipt.stage for receipt in caught.value.receipts] == [
        "research_plan",
        "evidence",
    ]
    assert len(provider.calls) == 2, "no call is made once the guard has refused"


def test_completion_stops_cleanly_and_keeps_the_proposal_s_receipts() -> None:
    golden = _golden()
    provider = SequenceProvider(_responses(golden))
    meter = StubMeter(budget=3)
    pipeline = FoundryPipeline(provider, meter=meter)

    proposed = pipeline.propose(
        "Help me improve my sourdough fermentation",
        acceptance_tasks=_acceptance_tasks(),
    )
    with pytest.raises(BudgetExhausted) as caught:
        pipeline.complete(proposed.proposal, golden.remix)

    assert caught.value.stage == "domain"
    assert [receipt.stage for receipt in caught.value.receipts] == [
        "research_plan",
        "evidence",
        "concepts",
    ]


def test_an_unmetered_pipeline_is_unchanged() -> None:
    """The meter is a collaborator, not a requirement; the goldens run without one."""
    golden = _golden()
    provider = SequenceProvider(_responses(golden))
    pipeline = FoundryPipeline(provider)

    proposed = pipeline.propose(
        "Help me improve my sourdough fermentation",
        acceptance_tasks=_acceptance_tasks(),
    )
    assert pipeline.complete(proposed.proposal, golden.remix).id == "sourdough-lab"


def _ledger(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE cost_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost_usd REAL NOT NULL,
            entry_id TEXT,
            created_at TEXT NOT NULL,
            tier TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    return path


def test_the_real_ledger_meter_writes_foundry_tier_rows(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "db" / "ledger.sqlite")
    guard = CostGuard(ledger, CostGuardConfig(daily_usd_cap=1.0, tier_caps={}))
    meter = LedgerCostMeter(guard, spec_id="sourdough-lab")

    assert meter.allow() is True
    meter.record(
        stage="domain",
        provider="anthropic",
        model="claude-opus-5",
        input_tokens=10_000,
        output_tokens=4_000,
    )

    conn = sqlite3.connect(ledger)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM cost_ledger").fetchone()
    conn.close()

    assert row["tier"] == FOUNDRY_COST_TIER
    assert row["entry_id"] == "foundry:sourdough-lab:domain"
    assert row["model"] == "claude-opus-5"
    # 10k in at $5/M plus 4k out at $25/M.
    assert row["cost_usd"] == pytest.approx(0.15)
    assert guard.spent_today(tier=FOUNDRY_COST_TIER) == pytest.approx(0.15)


def test_the_real_ledger_meter_refuses_once_the_daily_cap_is_spent(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "db" / "ledger.sqlite")
    guard = CostGuard(ledger, CostGuardConfig(daily_usd_cap=0.10, tier_caps={}))
    meter = LedgerCostMeter(guard, spec_id="sourdough-lab")

    meter.record(
        stage="research_plan",
        provider="anthropic",
        model="claude-opus-5",
        input_tokens=10_000,
        output_tokens=4_000,
    )
    assert meter.spent_usd == pytest.approx(0.15)
    assert meter.allow() is False


def test_foundry_spend_is_visible_to_the_undifferentiated_daily_cap(tmp_path: Path) -> None:
    """The point of the wiring: six sota calls used to be invisible here."""
    ledger = _ledger(tmp_path / "db" / "ledger.sqlite")
    guard = CostGuard(ledger, CostGuardConfig(daily_usd_cap=1.0, tier_caps={}))
    meter = LedgerCostMeter(guard)

    assert guard.spent_today() == 0.0
    for stage in ("research_plan", "evidence", "concepts"):
        meter.record(
            stage=stage,
            provider="anthropic",
            model="claude-opus-5",
            input_tokens=1_000,
            output_tokens=500,
        )
    assert guard.spent_today() > 0.0
    assert guard.spent_today() == pytest.approx(meter.spent_usd)
