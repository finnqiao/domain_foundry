"""The cross-cutting source slate must survive a growing registry.

Domain sources share incidental tokens with unrelated interests: a whisky source
carries the topic ``tasting_notes``, whose "notes" matches a sourdough research
plan. Ranking alone once let enough of those crowd provenance, accessibility, and
remix guidance past ``registered_limit``; the spec then failed closed with an
opaque "research cited unprovided sources". Retrieval now guarantees the slate.
"""

from __future__ import annotations

import yaml

from domain_foundry_core.foundry.loader import DEFAULT_REGISTRY, load_golden_specs
from domain_foundry_core.foundry.research import (
    _ALWAYS_RETRIEVE,
    KnowledgeRetriever,
    ResearchPlan,
)


def _sourdough_plan() -> ResearchPlan:
    golden = next(spec for spec in load_golden_specs() if spec.id == "sourdough-lab")
    return ResearchPlan(
        interest="sourdough fermentation",
        desired_outcome=golden.research.desired_outcome,
        practice_hypotheses=golden.research.practice[:3],
        queries=[
            "sourdough fermentation measurements open source",
            "sourdough starter data model",
            "sourdough baking workflow applications",
        ],
        vertical_keywords=["sourdough", "starter", "fermentation", "bake"],
        artifact_questions=["Do you already keep a bake notebook?"],
    )


def test_cross_cutting_slate_survives_unrelated_domain_sources() -> None:
    retrieved = KnowledgeRetriever(DEFAULT_REGISTRY).retrieve(_sourdough_plan())
    registered_ids = {str(source.get("id")) for source in retrieved.registered}

    registry = yaml.safe_load(DEFAULT_REGISTRY.read_text(encoding="utf-8")) or {}
    available = {
        str(source.get("id"))
        for source in registry.get("sources", [])
        if source.get("status") in {"approved", "reference_only"}
    }

    assert _ALWAYS_RETRIEVE & available <= registered_ids


def test_golden_citations_remain_retrievable() -> None:
    """A golden spec's own sources must come back for its own interest."""
    retrieved = KnowledgeRetriever(DEFAULT_REGISTRY).retrieve(_sourdough_plan())
    registered_ids = {str(source.get("id")) for source in retrieved.registered}

    golden = next(spec for spec in load_golden_specs() if spec.id == "sourdough-lab")
    assert set(golden.source_ids) <= registered_ids


def test_registered_set_respects_its_limit_when_uncrowded() -> None:
    retrieved = KnowledgeRetriever(DEFAULT_REGISTRY).retrieve(_sourdough_plan())
    assert len(retrieved.registered) <= 16


def test_tight_limit_keeps_both_guarantees_and_adds_no_filler() -> None:
    """A limit below the guaranteed floor yields the guarantees, and nothing else.

    The slate and the vertical evidence are floors rather than preferences, so a
    caller asking for four sources still gets every one of them. What a tight limit
    must not do is pull in unrelated filler on top.
    """
    narrowed = KnowledgeRetriever(DEFAULT_REGISTRY).retrieve(_sourdough_plan(), registered_limit=4)
    registered_ids = {str(source.get("id")) for source in narrowed.registered}

    assert "sourdough_ai" in registered_ids, "vertical evidence must survive the floor"

    unpinned = registered_ids - _ALWAYS_RETRIEVE
    assert unpinned == {"sourdough_ai"}, (
        f"tight limit should yield only the best vertical match, got {sorted(unpinned)}"
    )
