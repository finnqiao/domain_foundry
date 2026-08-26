"""Look payload projection (HTML on for HTTP, off for MCP/hermes)."""

from __future__ import annotations

from domain_foundry_core.packs.loader import bundled_packs_root
from domain_foundry_core.wizard.engine import (
    analog_covers_hero,
    bundled_view_blocks,
    idea_card_to_node,
    invent_idea_cards,
    looks_public,
)


def test_looks_public_strips_html_and_keeps_pitch():
    looks = [
        {
            "idea_id": "invented.lego.shelf",
            "title": "Lego shelf",
            "hero_job": "media_dex",
            "round": 2,
            "pitch": "A dex of the lego you keep, with photos.",
            "html": "<!doctype html><html><body>huge</body></html>",
            "jobs": ["catalog", "media_dex"],
        }
    ]
    slim = looks_public(looks, include_html=False)
    assert slim == [
        {
            "idea_id": "invented.lego.shelf",
            "title": "Lego shelf",
            "hero_job": "media_dex",
            "round": 2,
            "pitch": "A dex of the lego you keep, with photos.",
            "fallback_reason": None,
        }
    ]
    fat = looks_public(looks, include_html=True)
    assert fat[0]["html"].startswith("<!doctype html>")
    assert "jobs" in fat[0]
    # Original look dict is not mutated.
    assert "html" in looks[0]


def test_invent_idea_cards_are_domain_agnostic():
    for goal, token in (
        ("track my whisky", "whisky"),
        ("track my lego builds", "lego"),
        ("warhammer painting army", "warhammer"),
    ):
        cards = invent_idea_cards(goal)
        assert len(cards) == 3
        titles = " ".join(c["title"].lower() for c in cards)
        assert token in titles
        assert f"invented.{token}.shelf" == cards[0]["id"]
        assert cards[0]["jobs"] == ["catalog", "media_dex"]
        assert cards[1]["jobs"] == ["event_log"]
        assert cards[2]["jobs"] == ["improvement"]
        node = idea_card_to_node(cards[0])
        assert node.id == cards[0]["id"]
        assert node.analog_pack is None
        assert "catalog" in node.jobs


def test_analog_covers_hero_matches_required_live_views():
    sourdough = bundled_view_blocks("sourdough")
    assert analog_covers_hero(sourdough, "improvement")
    assert analog_covers_hero(sourdough, "media_dex")
    travel = bundled_view_blocks("travel")
    assert not analog_covers_hero(travel, "atlas")
    assert analog_covers_hero(travel, "event_log")
    assert (bundled_packs_root() / "sourdough" / "projections.yaml").is_file()
