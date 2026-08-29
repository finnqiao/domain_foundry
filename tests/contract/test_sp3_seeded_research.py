"""SP3: what the user seeded, what was read, and what was recalled stay apart.

June seeds two things for one build: a spreadsheet of her own tidepool walks,
and a link to a field guide she trusts. The brief that comes out has to keep
three kinds of material distinguishable, because they mean different things.

* The field guide is a source. It gets cited, with its link and its date, and it
  says plainly that nobody has reviewed it yet.
* The spreadsheet is not a source. It is June's own record. It proves nothing to
  anyone else, it is never cited, and it never leaves her machine. It reaches
  the brief as one of her existing artifacts, which is what it is.
* Anything the model supplied is marked, so she can always tell which is which.

Everything runs against a stub model. There are no keys here and none are needed:
the retrieval, the validation and the reference-closure checks are all real.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from domain_foundry_core.foundry.models import ResearchBrief, SeedProvenance
from domain_foundry_core.foundry.pipeline import AcceptanceTask, FoundryPipeline
from domain_foundry_core.foundry.research import (
    SEED_LINK_LICENSE,
    KnowledgeRetriever,
    claim_tiers,
    enrich_brief,
    personal_artifact_lines,
    seed_link_candidates,
)
from domain_foundry_core.llm.provider import CompletionResult, LLMProvider, TokenUsage

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "examples" / "seed-fixtures"

GOAL = "Keep track of what I find in the tidepools and when it is worth going"

FIELD_GUIDE_URL = "https://example.org/north-coast-intertidal-guide"
LOG_COLUMNS = ["date", "time", "spot", "species", "count", "tide_height_m", "notes"]


# --------------------------------------------------------------------------- #
# The two seeds
# --------------------------------------------------------------------------- #


def _personal_log() -> SeedProvenance:
    """June's own spreadsheet. Never a source, never shareable."""
    return SeedProvenance(
        id="tidepool_log",
        kind="personal_upload",
        label="Tidepool log spreadsheet",
        location="tidepool-log.xlsx",
        row_count=214,
        columns=list(LOG_COLUMNS),
    )


def _field_guide() -> SeedProvenance:
    """A page she pointed at. Citable, dated, not reviewed."""
    return SeedProvenance(
        id="field_guide",
        kind="public_link",
        label="North coast intertidal field guide",
        location=FIELD_GUIDE_URL,
        retrieved_at="2026-08-28",
    )


def _seeds() -> list[SeedProvenance]:
    return [_personal_log(), _field_guide()]


def _acceptance_tasks() -> list[AcceptanceTask]:
    return [
        AcceptanceTask(
            input="Record a walk and the species found in it.",
            expected="The walk and its finds are stored together and both are visible.",
        ),
        AcceptanceTask(
            input="Ask which species I have never found at a given spot.",
            expected="The app lists what is missing at that spot without inventing sightings.",
        ),
    ]


# --------------------------------------------------------------------------- #
# A stub that answers each stage from what it was actually shown
# --------------------------------------------------------------------------- #


class SeededStubProvider(LLMProvider):
    """Replays a plausible answer per stage, built from the real payload.

    It never invents a source id: the evidence stage cites whatever the
    retriever put in front of it, which is what makes the pipeline's own
    reference-closure check do real work here.
    """

    name = "sp3-stub"

    def __init__(self) -> None:
        self.stages: list[str] = []
        self.cited: list[str] = []

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
        payload = json.loads(user)
        self.stages.append(title)
        data = self._answer(title, payload)
        return CompletionResult(
            data=data,
            usage=TokenUsage(
                input_tokens=100,
                output_tokens=50,
                model="stub",
                tier=tier,
                provider=self.name,
            ),
        )

    def _answer(self, title: str, payload: dict[str, Any]) -> dict[str, Any]:
        if title == "ResearchPlan":
            return {
                "interest": "tidepooling on the north coast",
                "desired_outcome": "Know when to walk and what I have already found",
                "practice_hypotheses": [
                    "Walks are planned around the low tide window",
                    "Finds are identified against a field guide",
                    "The same handful of spots come up again and again",
                ],
                "queries": [
                    "intertidal species identification guide",
                    "tidepool survey data model open source",
                    "tide window planning",
                ],
                "vertical_keywords": ["tidepool", "intertidal", "nudibranch", "tide"],
                "artifact_questions": ["What do you write down after a walk?"],
                "constraints": [],
            }
        if title == "ResearchSynthesis":
            return self._synthesis(payload)
        if title in {"SoleConcept", "ConceptSet"}:
            return self._concepts(payload, count=1 if title == "SoleConcept" else 3)
        raise AssertionError(f"unexpected stage schema {title!r}")

    def _synthesis(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidates = payload["candidates"]
        source_ids = [str(item["id"]) for item in candidates]
        self.cited = source_ids
        principles = [str(item["id"]) for item in payload["principles"]][:8]
        # A real synthesis draws on everything it was shown. Registry records
        # carry no ``kind``; seeded pages and recall do, so this spans all three
        # rather than stopping at whatever happened to be listed first.
        registry = [str(item["id"]) for item in candidates if "kind" not in item][:3]
        other = [str(item["id"]) for item in candidates if "kind" in item]
        evidence = [
            {
                "id": f"ev{index}",
                "source_id": source_id,
                "claim": f"A bounded claim drawn from {source_id}.",
                "use": "fact",
            }
            for index, source_id in enumerate([*registry, *other], start=1)
        ]
        return {
            "title": "Tidepool Walks",
            "research": {
                "interest": "tidepooling on the north coast",
                "desired_outcome": "Know when to walk and what I have already found",
                "practice": [
                    "Walk a spot on a low tide",
                    "Identify what turned up",
                ],
                "existing_artifacts": [],
                "constraints": [],
                "open_questions": ["Which spots repeat?"],
                "usage_context": ["Outdoors, on a phone, hands cold and wet"],
                "first_value": "One walk recorded and its finds listed.",
            },
            "source_ids": source_ids,
            "principle_ids": principles,
            "evidence": evidence,
        }

    def _concepts(self, payload: dict[str, Any], *, count: int) -> dict[str, Any]:
        evidence_ids = [str(item["id"]) for item in payload["evidence"]][:2]
        shapes = [
            ("session", "walk", "record one walk at a time"),
            ("split", "catalog", "browse what is found against what is missing"),
            ("canvas", "spot", "move between places on a map"),
        ]
        return {
            "concepts": [
                {
                    "id": f"concept-{index}",
                    "title": f"Concept {index}: {noun}",
                    "thesis": f"The app is organised around the {noun}.",
                    "primary_loop": loop,
                    "primary_affordance": topology,
                    "differentiator": f"The {noun} is the thing you land on first.",
                    "feature_boundary": [f"in: the {noun}", "out: anything else"],
                    "workflow_ids": [f"wf_{noun}"],
                    "evidence_ids": evidence_ids,
                    "tradeoffs": [f"Everything that is not a {noun} is one step further away."],
                }
                for index, (topology, noun, loop) in enumerate(shapes[:count], start=1)
            ]
        }


# --------------------------------------------------------------------------- #
# The seeds on their own
# --------------------------------------------------------------------------- #


def test_a_personal_upload_never_becomes_a_source() -> None:
    assert seed_link_candidates([_personal_log()]) == []
    assert _personal_log().shareable is False

    lines = personal_artifact_lines(_seeds())
    assert len(lines) == 1
    assert "Tidepool log spreadsheet" in lines[0]
    assert "214 rows" in lines[0]
    # The field guide is not an artifact of hers; it is a source.
    assert "field guide" not in lines[0].casefold()


def test_a_seeded_page_is_cited_dated_and_says_it_is_unreviewed() -> None:
    candidate = seed_link_candidates([_field_guide()])[0]

    assert candidate.source.url == FIELD_GUIDE_URL
    assert candidate.source.retrieved_at == "2026-08-28"
    assert candidate.source.license == SEED_LINK_LICENSE
    assert candidate.source.status == "reference_only"
    assert candidate.source.tier != "model_knowledge"
    assert "not reviewed yet" in candidate.excerpt


# --------------------------------------------------------------------------- #
# SP3 itself
# --------------------------------------------------------------------------- #


def _run(seeds: list[SeedProvenance]) -> tuple[Any, SeededStubProvider, Any]:
    provider = SeededStubProvider()
    retriever = KnowledgeRetriever(seeds=seeds)
    knowledge = retriever.retrieve(
        # The plan the stub will produce, retrieved once up front so the test can
        # assert against the same retrieval the pipeline performs.
        _plan(),
        allow_model_knowledge=True,
    )
    pipeline = FoundryPipeline(provider, retriever=retriever, allow_model_knowledge=True)
    proposed = pipeline.propose(GOAL, acceptance_tasks=_acceptance_tasks(), concept_count=1)
    return proposed, provider, knowledge


def _plan() -> Any:
    from domain_foundry_core.foundry.research import ResearchPlan

    return ResearchPlan.model_validate(
        SeededStubProvider()._answer("ResearchPlan", {})  # noqa: SLF001
    )


def test_sp3_the_three_kinds_of_material_stay_distinguishable() -> None:
    seeds = _seeds()
    proposed, _provider, knowledge = _run(seeds)
    proposal = proposed.proposal

    # 1. Evidence cites the guide, with its link.
    seeded_ids = set(knowledge.seeded_ids)
    assert seeded_ids, "the seeded page must reach the candidate set"
    guide_id = next(iter(seeded_ids))
    assert guide_id in proposal.source_ids
    guide = next(item for item in proposal.source_snapshots if item.id == guide_id)
    assert guide.url == FIELD_GUIDE_URL
    assert guide.license == SEED_LINK_LICENSE

    # 2. Model claims are present and marked, and cannot pass as retrieved.
    recalled = [item for item in proposal.source_snapshots if item.tier == "model_knowledge"]
    assert recalled, "the third path was taken, so recall must be in the run"
    for item in recalled:
        assert item.url is None
        assert item.origin == "model_recall"
        assert item.status == "reference_only"

    # 3. The run is labelled by the weakest thing in it, never upward.
    assert proposal.receipt.evidence_tier == "model_knowledge"

    # 4. Claim by claim, a reader can tell which is which.
    tiers = claim_tiers(proposal.evidence, knowledge)
    assert set(tiers.values()) >= {"live_search", "model_knowledge"}
    by_source = {item.id: item.source_id for item in proposal.evidence}
    guide_claims = [key for key, source in by_source.items() if source == guide_id]
    assert guide_claims and all(tiers[key] == "live_search" for key in guide_claims)

    # 5. Nothing from the spreadsheet is a source, anywhere in the output.
    text = proposal.model_dump_json()
    assert "tidepool-log.xlsx" not in text
    for snapshot in proposal.source_snapshots:
        assert "tidepool_log" not in snapshot.id


def test_sp3_the_users_own_log_reaches_the_brief_as_her_artifact() -> None:
    seeds = _seeds()
    proposed, _provider, _knowledge = _run(seeds)

    brief = enrich_brief(proposed.proposal.research, seeds=seeds)

    assert isinstance(brief, ResearchBrief)
    joined = " ".join(brief.existing_artifacts)
    assert "Tidepool log spreadsheet" in joined
    assert "214 rows" in joined
    assert "spot" in joined and "species" in joined
    # Both seeds are recorded, and only one of them may ever travel.
    assert {item.id for item in brief.seeds} == {"tidepool_log", "field_guide"}
    shareable = {item.id for item in brief.seeds if item.shareable}
    assert shareable == {"field_guide"}


def test_sp3_declining_every_on_ramp_still_fails_closed() -> None:
    """No seeds and no consent is still the honest dead end, not a scaffold."""
    from domain_foundry_core.foundry.research import ResearchUnavailable

    with pytest.raises(ResearchUnavailable, match="Three ways forward"):
        KnowledgeRetriever().retrieve(_plan())


def test_sp3_from_lane_es_tidepool_fixture() -> None:
    """SP3 off the real fixture.

    Lane F wrote this as xfail while Lane E's package was still landing. Both
    lanes are in now and the package imports, so the integrator flipped it to a
    plain test: the seam is proved, not hoped for.
    """

    from domain_foundry_core.seed import read_seed  # noqa: PLC0415

    read = read_seed(FIXTURES / "tidepool-log.xlsx")
    seeds = [read.provenance, _field_guide()]

    assert read.provenance.kind == "personal_upload"
    assert read.provenance.shareable is False

    proposed, _provider, knowledge = _run(seeds)
    brief = enrich_brief(proposed.proposal.research, seeds=seeds)

    assert knowledge.seeded_ids
    assert any("tidepool" in line.casefold() for line in brief.existing_artifacts)
    assert [item.tier for item in proposed.proposal.source_snapshots].count("model_knowledge") > 0
