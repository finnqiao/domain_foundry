"""Lane F1: an unindexed passion stops being a dead end.

Before this, an interest the reviewed sources had never heard of got one error
naming a search adapter. There are three real ways forward and the user is told
all three. The third one, building from what the model knows, is reachable now,
but only because someone picked it, and everything it produces is marked.
"""

from __future__ import annotations

import pytest

from domain_foundry_core.foundry.models import EvidenceCitation, SeedProvenance
from domain_foundry_core.foundry.research import (
    MODEL_CLAIM_MARK,
    MODEL_MARKING_NOTE,
    THREE_PATHS,
    KnowledgeRetriever,
    ResearchPlan,
    ResearchUnavailable,
    claim_tiers,
    three_path_message,
)


def _out_of_corpus_plan() -> ResearchPlan:
    return ResearchPlan(
        interest="tidepooling on the north coast",
        desired_outcome="Know which pools to walk and what I have already found",
        practice_hypotheses=[
            "Walks are planned around low tide",
            "Finds are identified against a field guide",
        ],
        queries=[
            "tidepool species identification",
            "intertidal survey data model",
            "tide window planning app",
        ],
        vertical_keywords=["tidepool", "intertidal", "nudibranch"],
        artifact_questions=["What do you already write down after a walk?"],
    )


# --------------------------------------------------------------------------- #
# The three-path message
# --------------------------------------------------------------------------- #


def test_the_message_names_three_concrete_on_ramps() -> None:
    message = three_path_message("tidepooling")

    assert "tidepooling" in message
    for path in THREE_PATHS:
        assert path in message
    # Each ask names exactly what to provide, rather than asking for "sources".
    assert "spreadsheet" in message
    assert "field guide" in message
    assert "marked, so you can always tell which is which" in message


def test_the_message_keeps_the_copy_rules() -> None:
    message = three_path_message("competitive cloud sculpting")

    assert "—" not in message, "no em dashes in user-facing copy"
    for banned in ("free", "cost", "pricing", "upgrade", "$"):
        assert banned not in message.casefold()
    # No jargon leaking out of the engine.
    for banned in ("adapter", "corpus", "registry", "provenance", "tier"):
        assert banned not in message.casefold()


def test_declining_every_on_ramp_still_fails_closed() -> None:
    """The floor is unchanged: no consent, no build."""
    with pytest.raises(ResearchUnavailable, match="Three ways forward") as caught:
        KnowledgeRetriever().retrieve(_out_of_corpus_plan())

    assert caught.value.paths == THREE_PATHS


# --------------------------------------------------------------------------- #
# The third path, taken
# --------------------------------------------------------------------------- #


def test_consent_reaches_model_knowledge_and_every_snapshot_is_marked() -> None:
    retrieved = KnowledgeRetriever().retrieve(_out_of_corpus_plan(), allow_model_knowledge=True)

    assert retrieved.tier == "model_knowledge"
    assert retrieved.external
    for candidate in retrieved.external:
        source = candidate.source
        assert source.tier == "model_knowledge"
        assert source.origin == "model_recall"
        assert source.status == "reference_only"
        assert source.url is None
        assert retrieved.tier_of(source.id) == "model_knowledge"


def test_the_marking_copy_is_plain_and_not_scary() -> None:
    for line in (MODEL_CLAIM_MARK, MODEL_MARKING_NOTE):
        assert "—" not in line
        for banned in ("hallucinat", "danger", "warning", "unreliable", "risk"):
            assert banned not in line.casefold()
    assert "always tell which is which" in MODEL_MARKING_NOTE


def test_the_receipt_can_say_which_tier_every_claim_came_from() -> None:
    plan = _out_of_corpus_plan()
    retrieved = KnowledgeRetriever().retrieve(plan, allow_model_knowledge=True)
    recalled = retrieved.external[0].source.id
    reviewed = str(retrieved.registered[0]["id"])

    tiers = claim_tiers(
        [
            EvidenceCitation(id="e1", source_id=recalled, claim="a recalled claim", use="fact"),
            EvidenceCitation(id="e2", source_id=reviewed, claim="a reviewed claim", use="pattern"),
        ],
        retrieved,
    )

    assert tiers == {"e1": "model_knowledge", "e2": "reviewed_corpus"}


def test_a_seeded_link_is_neither_reviewed_nor_recalled() -> None:
    seed = SeedProvenance(
        id="guide",
        kind="public_link",
        label="North coast intertidal field guide",
        location="https://example.org/intertidal-guide",
    )
    retrieved = KnowledgeRetriever(seeds=[seed]).retrieve(_out_of_corpus_plan())

    assert retrieved.seeded_ids, "a seeded page opens the gate on its own"
    seeded_id = retrieved.seeded_ids[0]
    assert retrieved.tier_of(seeded_id) == "live_search"
    snapshot = next(item.source for item in retrieved.external if item.source.id == seeded_id)
    assert snapshot.url == "https://example.org/intertidal-guide"
    assert snapshot.status == "reference_only"
    assert snapshot.license == "unknown-until-reviewed"
