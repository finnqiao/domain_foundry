"""The fork must earn its answer or admit it has none.

Six goals in the 50-interest audit landed in a confidently wrong neighbourhood
because any score above zero beat "I don't know": one generic token inside an
alias, or a node id read as if it were vocabulary, was enough. These tests pin
the two rules that stop it — ids are not words, and a resemblance is not a
neighbourhood — against the exact goals that failed.
"""

from __future__ import annotations

import pytest

from domain_foundry_core.atlas.loader import load_atlas
from domain_foundry_core.atlas.query import (
    _goal_tokens,
    _node_terms,
    query_neighborhood,
    score_node_detail,
)


def _cursor(goal: str) -> str | None:
    return query_neighborhood(goal).get("cursor")


@pytest.mark.parametrize(
    ("goal", "forbidden"),
    [
        ("whisky tasting notes", "making.dev"),
        ("i play vinyl records", "sports.soccer"),
        ("chess openings and games I play", "sports.soccer"),
        ("model train layout progress", "diving.freediving"),
        ("fish in my aquarium tank", "diving"),
        ("yoga practice", "music"),
    ],
)
def test_audit_snap_goals_no_longer_reach_their_wrong_neighbourhood(
    goal: str, forbidden: str
) -> None:
    """Covered or not, a goal must never land in the neighbourhood that misled it.

    Whisky and vinyl are now indexed (``food.drinks``, ``music.records``), which
    is a stronger answer than silence — but the failure this pins is landing on
    ``making.dev`` and ``sports.soccer``, and that must stay impossible either way.
    """
    cursor = _cursor(goal)
    assert not (cursor and (cursor == forbidden or cursor.startswith(f"{forbidden}."))), (
        f"{goal!r} snapped to {cursor!r}"
    )


@pytest.mark.parametrize(
    "goal",
    [
        "chess openings and games I play",
        "model train layout progress",
        "fish in my aquarium tank",
        "track my lego builds",
        "ham radio contacts",
        "pottery wheel throwing",
        "astronomy observing nights",
        "fountain pens and ink",
    ],
)
def test_goals_the_atlas_does_not_cover_report_unindexed(goal: str) -> None:
    """Honest silence, not a nearest-sounding shelf.

    The principle is "an uncovered goal reports unindexed rather than snapping",
    not "these particular goals stay uncovered forever". Whisky and vinyl used
    to sit in this list and were the only examples of their own coverage gap;
    the atlas now carries ``food.drinks`` and ``music.records`` on the merits
    (whisky ships a hand-authored showcase spec; records are a mainstream music
    vertical). They moved to the snap test above, which still holds them off
    ``making.dev`` and ``sports.soccer``. The list is deliberately long so the
    principle no longer rests on any single example.
    """
    assert query_neighborhood(goal).get("unindexed") is True


def test_yoga_reaches_wellness_rather_than_instrument_practice() -> None:
    """'practice' is a word two neighbourhoods share; only one is about yoga."""
    cursor = _cursor("yoga practice")
    assert cursor is not None
    assert cursor.split(".")[0] == "wellness"


def test_node_ids_are_not_scored_as_vocabulary() -> None:
    """ "learn to juggle" must not answer to `learning.languages`.

    The id segment "learning" contains "learn". Reading ids as words made that a
    match, and the practice kind bonus then tripled it.
    """
    graph = load_atlas()
    node = graph.nodes["learning.languages"]
    assert "learning.languages" not in _node_terms(node)

    tokens = _goal_tokens(graph, "learn to juggle")
    assert score_node_detail(node, tokens, "learn to juggle").strong is False
    assert query_neighborhood("learn to juggle").get("unindexed") is True


def test_weak_resemblance_ranks_but_never_qualifies() -> None:
    """A prefix overlap can order candidates; it cannot create one."""
    graph = load_atlas()
    node = graph.nodes["learning.languages"]
    weak_only = score_node_detail(node, {"learning"}, "learning")

    if weak_only.weak:
        assert weak_only.strong is False, "weak evidence must not qualify a node"

    named = score_node_detail(
        node, _goal_tokens(graph, "japanese anki reviews"), "japanese anki reviews"
    )
    assert named.strong is True


def test_kind_bonus_cannot_manufacture_a_match() -> None:
    graph = load_atlas()
    for node in graph.nodes.values():
        detail = score_node_detail(node, {"xyzzy", "plugh", "foobar"}, "xyzzy plugh foobar")
        assert detail.total == 0, f"{node.id} scored on nonsense"


def test_indexed_goals_still_land_where_they_belong() -> None:
    """The floor must not cost the goals that already worked."""
    expected = {
        "i have a log of sourdough bakes": "food",
        "pour over coffee brews": "food",
        "soccer training sessions": "sports",
        "scuba dive log with air": "diving",
        "watering log for houseplants": "plants",
        "birdwatching this weekend": "animals",
        "i collect pokemon cards": "collecting",
        "guitar practice": "music",
    }
    for goal, bucket in expected.items():
        cursor = _cursor(goal)
        assert cursor is not None, f"{goal!r} went unindexed"
        assert cursor.split(".")[0] == bucket, f"{goal!r} -> {cursor!r}"
