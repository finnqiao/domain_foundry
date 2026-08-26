"""Picking the suggested idea must not depend on how you say yes.

The fork prints an idea list with one marked "(suggested)". Typing `1` used to
index into raw display order while `yes` took a different path that preferred the
highlighted card, so the same screen built different packs depending on the
user's phrasing. The pokemon case in the 50-interest audit lost its Card dex that
way. Display order is now the single source of truth: highlighted first, and both
replies take the first displayed idea.
"""

from __future__ import annotations

import pytest

from domain_foundry_core.atlas.query import query_neighborhood

GOALS = [
    "a photo dex of my plants",
    "track what i cook",
    "i collect pokemon cards",
    "scuba dive log with air",
    "pour over coffee brews",
]


def _committed(api, goal: str, reply: str) -> list[str]:
    turn = api.new_domain(goal)
    session = turn["session_id"]
    turn = api.wizard_reply(session, reply)
    return [look.get("idea_id") for look in (turn.get("looks") or [])]


@pytest.mark.parametrize("goal", GOALS)
def test_the_suggested_idea_is_listed_first(goal: str) -> None:
    ideas = query_neighborhood(goal).get("ideas") or []
    if not ideas:
        pytest.skip(f"{goal!r} offers no idea cards")
    highlighted = [idea["id"] for idea in ideas if idea.get("highlighted")]
    if not highlighted:
        pytest.skip(f"{goal!r} highlights nothing")
    assert ideas[0]["id"] in highlighted, (
        f"{goal!r} shows {ideas[0]['id']} first but suggests {highlighted}"
    )


@pytest.mark.parametrize("goal", GOALS)
def test_one_and_yes_commit_the_same_idea(goal: str, workspace) -> None:
    from domain_foundry_core.api.harness import HarnessAPI

    api = HarnessAPI(workspace.home)
    api.init()

    numeric = _committed(api, goal, "1")
    affirmative = _committed(api, goal, "yes")

    assert numeric, f"{goal!r} committed nothing for '1'"
    assert numeric == affirmative, f"{goal!r}: '1' built {numeric} but 'yes' built {affirmative}"


def test_pokemon_builds_the_card_dex_it_suggests(workspace) -> None:
    """The audit's exemplar: suggested Card dex, built Set completion."""
    from domain_foundry_core.api.harness import HarnessAPI

    api = HarnessAPI(workspace.home)
    api.init()

    ideas = query_neighborhood("i collect pokemon cards").get("ideas") or []
    assert ideas, "pokemon offers no ideas"
    assert ideas[0].get("highlighted") is True

    assert _committed(api, "i collect pokemon cards", "1") == [ideas[0]["id"]]
