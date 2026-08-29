"""E4 and E5: what a seed tells the brief, and how far down the pipeline it gets.

What travels is shapes and counts. A place name or a species name out of somebody's
own spreadsheet is their vocabulary, so the count of them goes and the names stay.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from domain_foundry_core.foundry.loader import load_golden_specs
from domain_foundry_core.foundry.models import ResearchBrief, SeedProvenance
from domain_foundry_core.foundry.pipeline import AcceptanceTask, FoundryPipeline
from domain_foundry_core.llm.provider import CompletionResult, LLMProvider, TokenUsage
from domain_foundry_core.security.redact import contains_potential_secret
from domain_foundry_core.seed.brief import (
    SEED_ASK,
    declined_seeding,
    seed_artifact_lines,
    seed_brief_inputs,
)
from domain_foundry_core.seed.models import summarize
from domain_foundry_core.seed.readers import read_seed

FIXTURES = Path(__file__).resolve().parents[2] / "examples" / "seed-fixtures"


class _SequenceProvider(LLMProvider):
    name = "sequence-seed-test"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, *, system, user, schema=None, model=None, tier=None):
        self.calls.append({"system": system, "user": user, "schema": schema})
        return CompletionResult(data=self.responses.popleft(), usage=TokenUsage())

    def payload_for(self, stage_index: int) -> str:
        return self.calls[stage_index]["user"]


def _acceptance_tasks() -> list[AcceptanceTask]:
    return [
        AcceptanceTask(
            input="Record a real feeding and see whether the starter is ready.",
            expected="The feeding is linked to the starter and readiness is visible.",
        ),
        AcceptanceTask(
            input="Compare two bakes that used different fermentation choices.",
            expected="The app shows both bakes without losing either.",
        ),
    ]


def _golden_responses(seeds: list[SeedProvenance] | None = None):
    """The recorded shape of a full run, so the test spends nothing on a model."""

    golden = next(spec for spec in load_golden_specs() if spec.id == "sourdough-lab")
    research = golden.research.model_dump(mode="json")
    if seeds is not None:
        research["seeds"] = [item.model_dump(mode="json") for item in seeds]
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
    responses = [
        plan,
        {
            "title": golden.title,
            "research": research,
            "source_ids": golden.source_ids,
            "principle_ids": golden.principle_ids,
            "evidence": [item.model_dump(mode="json") for item in golden.evidence],
        },
        {"concepts": [item.model_dump(mode="json") for item in golden.concepts]},
        {"domain": golden.domain.model_dump(mode="json")},
        {"experience": golden.experience.model_dump(mode="json")},
        {
            "implementation": golden.implementation.model_dump(mode="json"),
            "derivations": [item.model_dump(mode="json") for item in golden.derivations],
        },
    ]
    return golden, responses


# --------------------------------------------------------------------- the lines


def test_a_seeded_log_becomes_short_lines_a_brief_can_take():
    read = read_seed(FIXTURES / "tidepool-log.xlsx")
    lines = seed_artifact_lines(summarize(read))

    assert any("214 rows" in line for line in lines)
    assert any("2024-04-05" in line and "2026-06-10" in line for line in lines)
    assert any("7 values keep coming back in Place" in line for line in lines)
    assert any("9 values keep coming back in Species" in line for line in lines)


def test_the_lines_carry_counts_and_never_the_records():
    """The sharing line at the row level: her places and species stay home."""

    read = read_seed(FIXTURES / "tidepool-log.xlsx")
    lines = " ".join(seed_artifact_lines(summarize(read)))

    for private in ("Pillar Point", "ochre sea star", "Duxbury Reef", "gumboot chiton"):
        assert private not in lines


def test_a_page_you_pointed_at_is_described_as_a_page():
    read = read_seed(FIXTURES / "field-guide.html")
    lines = seed_artifact_lines(summarize(read))

    assert lines[0].startswith("A page I trust: Rocky shore field guide: sea stars and anemones.")


def test_the_lines_fit_inside_what_the_pipeline_accepts():
    """A brief takes twenty artifacts of two thousand characters. Seeds leave room."""

    reads = [
        read_seed(FIXTURES / "tidepool-log.xlsx"),
        read_seed(FIXTURES / "field-guide.html"),
    ]
    inputs = seed_brief_inputs(reads)

    assert len(inputs.artifacts) <= 20
    assert all(len(line) <= 2_000 for line in inputs.artifacts)
    assert not any(contains_potential_secret(line) for line in inputs.artifacts)


def test_a_bundle_keeps_the_personal_and_the_public_apart():
    reads = [
        read_seed(FIXTURES / "tidepool-log.xlsx"),
        read_seed(FIXTURES / "field-guide.html"),
    ]
    inputs = seed_brief_inputs(reads)

    by_kind = {seed.kind: seed for seed in inputs.seeds}
    assert set(by_kind) == {"personal_upload", "public_link"}
    assert by_kind["personal_upload"].shareable is False
    assert by_kind["public_link"].shareable is True
    assert by_kind["public_link"].location


def test_the_seeds_go_onto_a_research_brief_and_validate():
    reads = [read_seed(FIXTURES / "tidepool-log.xlsx")]
    inputs = seed_brief_inputs(reads)

    brief = ResearchBrief(
        interest="tidepooling",
        desired_outcome="See what I have found and what I have not.",
        practice=["Walk the rocks at low tide", "Write down what I saw"],
        usage_context=["On the rocks, one hand free"],
        first_value="My own log, already in there.",
        seeds=inputs.seeds,
    )

    assert [seed.kind for seed in brief.seeds] == ["personal_upload"]
    assert brief.seeds[0].shareable is False


# ----------------------------------------------------------------------- the ask


def test_the_ask_names_exactly_what_helps():
    for named in ("spreadsheet", "notes folder", "photos", "export", "field guide"):
        assert named in SEED_ASK
    # No em dashes, no talk of money, no cleverness.
    assert "—" not in SEED_ASK
    assert "free" not in SEED_ASK.casefold()


def test_the_ask_offers_a_way_past_it():
    assert "just build" in SEED_ASK
    assert declined_seeding("just build") is True
    assert declined_seeding("skip") is True
    assert declined_seeding("here is my spreadsheet") is False


# ------------------------------------------------------- how far down it reaches


def test_the_seed_summary_reaches_the_stages_that_design_the_app():
    read = read_seed(FIXTURES / "tidepool-log.xlsx")
    inputs = seed_brief_inputs([read])
    _golden, responses = _golden_responses()
    provider = _SequenceProvider(responses)

    proposed = FoundryPipeline(provider).propose(
        "Help me improve my sourdough fermentation",
        artifacts=inputs.artifacts,
        acceptance_tasks=_acceptance_tasks(),
    )

    # Both research stages are shown what the person already keeps.
    for stage in (0, 1):
        payload = provider.payload_for(stage)
        assert "214 rows" in payload
        assert "keep coming back in Place" in payload
    assert proposed.proposal.artifacts == inputs.artifacts


def test_the_seed_provenance_reaches_the_domain_stage():
    """SP3's seed side: by the time the schema is designed, the marking is there.

    Lane F decides what research does with it. This proves it arrives.
    """

    read = read_seed(FIXTURES / "tidepool-log.xlsx")
    inputs = seed_brief_inputs([read])
    golden, responses = _golden_responses(seeds=inputs.seeds)
    provider = _SequenceProvider(responses)
    pipeline = FoundryPipeline(provider)

    proposed = pipeline.propose(
        "Help me improve my sourdough fermentation",
        artifacts=inputs.artifacts,
        acceptance_tasks=_acceptance_tasks(),
    )
    assert [seed.id for seed in proposed.proposal.research.seeds] == [read.provenance.id]

    pipeline.complete(proposed.proposal, golden.remix)

    domain_payload = json.loads(provider.payload_for(3).split("CONTEXT_JSON:", 1)[-1])
    seeds = domain_payload["research"]["seeds"]
    assert [seed["kind"] for seed in seeds] == ["personal_upload"]
    assert seeds[0]["license"] is None
