from __future__ import annotations

from collections import deque
from typing import Any

import pytest

from domain_foundry_core.foundry.loader import load_golden_specs
from domain_foundry_core.foundry.pipeline import AcceptanceTask, FoundryPipeline, PipelineError
from domain_foundry_core.foundry.research import ResearchUnavailable
from domain_foundry_core.llm.provider import CompletionResult, LLMProvider, TokenUsage


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
                input_tokens=100,
                output_tokens=50,
                model="test-reasoner",
                tier=tier,
                provider=self.name,
            ),
        )


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


def _responses() -> tuple[Any, list[dict[str, Any]]]:
    golden = next(spec for spec in load_golden_specs() if spec.id == "sourdough-lab")
    plan = {
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
    synthesis = {
        "title": golden.title,
        "research": golden.research.model_dump(mode="json"),
        "source_ids": golden.source_ids,
        "principle_ids": golden.principle_ids,
        "evidence": [item.model_dump(mode="json") for item in golden.evidence],
    }
    responses = [
        plan,
        synthesis,
        {"concepts": [item.model_dump(mode="json") for item in golden.concepts]},
        {"domain": golden.domain.model_dump(mode="json")},
        {"experience": golden.experience.model_dump(mode="json")},
        {
            "implementation": golden.implementation.model_dump(mode="json"),
            "derivations": [item.model_dump(mode="json") for item in golden.derivations],
        },
    ]
    return golden, responses


def test_staged_pipeline_proposes_then_compiles_one_closed_spec() -> None:
    golden, responses = _responses()
    provider = SequenceProvider(responses)
    pipeline = FoundryPipeline(provider)

    proposed = pipeline.propose(
        "Help me improve my sourdough fermentation",
        artifacts=["paper bake notebook"],
        acceptance_tasks=_acceptance_tasks(),
    )
    assert proposed.proposal.id == "sourdough-lab"
    assert len(proposed.proposal.concepts) == 3
    assert len(proposed.proposal.receipt.stages) == 3

    spec = pipeline.complete(proposed.proposal, golden.remix)
    assert spec.generation is not None
    assert [item.stage for item in spec.generation.stages] == [
        "research_plan",
        "evidence",
        "concepts",
        "domain",
        "experience",
        "delivery",
    ]
    assert {case.authored_by for case in spec.evaluation.cases} == {"user", "standard"}
    assert len(provider.calls) == 6
    assert all(call["tier"] == "sota" for call in provider.calls)
    assert all(call["schema"] for call in provider.calls)


def test_pipeline_rejects_a_model_invented_source_id() -> None:
    _golden, responses = _responses()
    responses[1]["source_ids"] = [*responses[1]["source_ids"], "invented_source"]
    provider = SequenceProvider(responses)

    with pytest.raises(PipelineError, match="unprovided sources"):
        FoundryPipeline(provider).propose(
            "Help me improve my sourdough fermentation",
            acceptance_tasks=_acceptance_tasks(),
        )


def test_pipeline_rejects_three_cosmetic_variants_of_one_concept() -> None:
    _golden, responses = _responses()
    concepts = responses[2]["concepts"]
    for index, concept in enumerate(concepts):
        concept["primary_loop"] = "Record an item and inspect the same overview"
        concept["primary_affordance"] = "The same dashboard card"
        concept["workflow_ids"] = ["same_workflow"]
        concept["title"] = f"Color variant {index}"
    provider = SequenceProvider(responses)

    with pytest.raises(PipelineError, match="concepts stage failed validation"):
        FoundryPipeline(provider).propose(
            "Help me improve my sourdough fermentation",
            acceptance_tasks=_acceptance_tasks(),
        )


def test_pipeline_refuses_an_unresearched_vertical_without_search() -> None:
    plan = {
        "interest": "competitive cloud sculpting",
        "desired_outcome": "Improve repeatable cloud sculptures",
        "practice_hypotheses": ["Shape clouds", "Compare outcomes"],
        "queries": ["cloud sculpting standard", "cloud sculpting software", "cloud sculpting schema"],
        "vertical_keywords": ["cloud", "sculpting"],
        "artifact_questions": ["What do you record?"],
        "constraints": [],
    }
    provider = SequenceProvider([plan])

    with pytest.raises(ResearchUnavailable, match="Three ways forward"):
        FoundryPipeline(provider).propose(
            "Track competitive cloud sculpting",
            acceptance_tasks=_acceptance_tasks(),
        )


def test_pipeline_refuses_to_send_potential_credentials_to_providers() -> None:
    provider = SequenceProvider([])

    with pytest.raises(PipelineError, match="Potential credential detected"):
        FoundryPipeline(provider).propose(
            "Build a starter journal with api_key=synthetic-secret-value",
            acceptance_tasks=_acceptance_tasks(),
        )

    assert provider.calls == []


def test_pipeline_refuses_model_generated_credentials_before_search() -> None:
    _golden, responses = _responses()
    responses[0]["queries"][0] = "api_key=synthetic-secret-value"
    provider = SequenceProvider(responses)

    with pytest.raises(PipelineError, match="search was not run"):
        FoundryPipeline(provider).propose(
            "Help me improve my sourdough fermentation",
            acceptance_tasks=_acceptance_tasks(),
        )

    assert len(provider.calls) == 1
