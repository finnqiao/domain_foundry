"""Idea atlas seed + neighborhood query."""

from __future__ import annotations

from pathlib import Path

from domain_foundry_core.atlas.loader import graph_stats, load_atlas, validate_atlas
from domain_foundry_core.atlas.query import (
    _content_tokens,
    _goal_tokens,
    query_neighborhood,
    score_node,
)


def _ids(cards: list[dict]) -> set[str]:
    return {c["id"] for c in cards}


def _titles(cards: list[dict]) -> str:
    return " ".join(c.get("title", "") for c in cards).lower()


def test_atlas_seed_loads_and_lints():
    graph = load_atlas()
    assert validate_atlas(graph) == []
    stats = graph_stats(graph)
    assert stats["buckets"] >= 15
    assert stats["ideas"] >= 30


def test_food_neighborhood_has_recipe_nutrition_and_map():
    nb = query_neighborhood("food")
    nearby = _ids(nb["refine"]) | _ids(nb["expand"]) | {nb["cursor"]}
    blob = _titles(nb["refine"] + nb["expand"] + nb["ideas"]) + " " + " ".join(nearby)
    assert "cooking" in blob or "food.cooking" in nearby
    assert "nutrition" in blob
    assert "dining" in blob or "map" in blob
    provenances = {i.get("provenance") for i in nb["ideas"]}
    assert "world" in provenances or "both" in provenances
    assert "foundry" in provenances or "both" in provenances
    assert any("recipe" in (i.get("title") or "").lower() for i in nb["ideas"])


def test_diving_neighborhood_includes_freediving_and_photography():
    for goal in ("diving", "scuba"):
        nb = query_neighborhood(goal)
        blob = _titles(nb["refine"] + nb["expand"]) + " " + " ".join(_ids(nb["refine"] + nb["expand"]))
        assert "freediving" in blob, (goal, blob)
        assert "photo" in blob, (goal, blob)
        ideas = _titles(nb["ideas"])
        assert "sac" in ideas or "air" in ideas or "dive log" in ideas
        assert "pokedex" in ideas or "species" in ideas
        assert any(i.get("world_analogs") for i in nb["ideas"])


def test_sports_branches_and_soccer_is_not_a_generic_workout():
    sports = query_neighborhood("sports")
    blob = _titles(sports["refine"] + sports["expand"])
    assert "soccer" in blob
    soccer = query_neighborhood("soccer")
    ideas = _titles(soccer["ideas"])
    assert "training" in ideas or "pickup" in ideas or "tactical" in ideas
    assert "workout" not in ideas or "training" in ideas


def test_recipe_tracker_highlights_recipe_and_still_offers_expand():
    nb = query_neighborhood("recipe tracker")
    highlighted = [i for i in nb["ideas"] if i.get("highlighted")]
    assert highlighted
    assert any("recipe" in (i["title"].lower()) for i in highlighted)
    blob = _titles(nb["ideas"] + nb["expand"] + nb["refine"])
    assert "cook" in blob or "dining" in blob or "map" in blob


def test_pokedex_of_cards_is_collecting_not_diving():
    nb = query_neighborhood("i want a pokedex of my cards")
    cursor = nb.get("cursor") or ""
    assert "diving" not in cursor
    titles = _titles(nb["ideas"])
    assert "card" in titles


def test_fountain_pens_are_unindexed_not_food():
    nb = query_neighborhood("fountain pens and ink")
    assert _unindexed(nb), nb.get("cursor")
    assert (nb.get("cursor") or "") != "food"


def test_short_token_ink_does_not_fuzzy_match_drinks():
    graph = load_atlas()
    food = graph.get("food")
    assert food is not None
    assert score_node(food, {"fountain", "pens", "ink"}, "fountain pens and ink") == 0


def test_pokemon_cards_lands_on_collecting_not_diving():
    nb = query_neighborhood("i collect pokemon cards")
    blob = (
        " ".join(b["id"] for b in nb["breadcrumb"])
        + " "
        + _titles(nb["ideas"] + nb["refine"] + nb["expand"])
        + " "
        + " ".join(_ids(nb["ideas"]))
    )
    assert "collecting" in blob or "card" in blob
    assert "diving" not in (nb.get("cursor") or "")
    titles = _titles(nb["ideas"])
    assert "card" in titles
    assert "set" in titles or "pull" in titles
    highlighted = [i for i in nb["ideas"] if i.get("highlighted")]
    assert any("card" in (i.get("title") or "").lower() for i in highlighted)


def test_underwater_animals_lands_near_pokedex():
    nb = query_neighborhood("I want to remember the animals I see underwater")
    blob = (
        " ".join(b["id"] for b in nb["breadcrumb"])
        + " "
        + _titles(nb["ideas"] + nb["refine"] + nb["expand"])
        + " "
        + " ".join(_ids(nb["ideas"]))
    )
    assert "pokedex" in blob or "species" in blob or "marine" in blob or "naturalism" in blob


def test_overlay_shadows_shipped_node(tmp_path: Path):
    overlay = tmp_path / "atlas"
    overlay.mkdir()
    overlay.joinpath("extra.yaml").write_text(
        """
nodes:
  - id: food
    kind: bucket
    title: Food (overlay)
    aliases: [cooking]
    pitch: Overlay pitch.
edges: []
""",
        encoding="utf-8",
    )
    graph = load_atlas(overlay)
    food = graph.get("food")
    assert food is not None
    assert food.title == "Food (overlay)"


def _unindexed(nb: dict) -> bool:
    return nb.get("unindexed") is True or not nb.get("cursor")


def test_unknown_goals_are_unindexed_not_wildlife():
    for goal in ("xyzzy plugh foobar", "track my lego builds", "warhammer painting"):
        nb = query_neighborhood(goal)
        assert _unindexed(nb), (goal, nb.get("cursor"))
        assert "wildlife" not in (nb.get("cursor") or "")
        assert "animals.wildlife" not in (nb.get("cursor") or "")


def test_kind_bonus_requires_token_or_alias_overlap():
    graph = load_atlas()
    wildlife = graph.get("animals.wildlife")
    assert wildlife is not None
    assert score_node(wildlife, {"xyzzy", "plugh", "foobar"}, "xyzzy plugh foobar") == 0
    assert score_node(wildlife, _content_tokens("track my lego builds"), "track my lego builds") == 0


def test_birdwatching_tokenizes_and_lands_on_wildlife():
    graph = load_atlas()
    tokens = _goal_tokens(graph, "birdwatching")
    assert "birdwatching" in tokens
    assert "bird" in tokens
    assert "watching" in tokens
    nb = query_neighborhood("birdwatching")
    assert nb.get("unindexed") is not True
    cursor = nb.get("cursor") or ""
    blob = (
        cursor
        + " "
        + " ".join(b["id"] for b in nb["breadcrumb"])
        + " "
        + _titles(nb["ideas"] + nb["refine"] + nb["expand"])
    )
    assert "wildlife" in blob
    wildlife = graph.get("animals.wildlife")
    assert wildlife is not None
    assert score_node(wildlife, tokens, "birdwatching") > 2


def test_sourdough_bakes_still_bake_lab():
    nb = query_neighborhood("i have a log of sourdough bakes")
    blob = (
        " ".join(b["id"] for b in nb["breadcrumb"])
        + " "
        + _titles(nb["ideas"] + nb["refine"] + nb["expand"])
        + " "
        + " ".join(_ids(nb["ideas"]))
    )
    assert "bake" in blob or "sourdough" in blob
    assert "soccer" not in (nb.get("cursor") or "")


def test_whisky_tasting_is_not_dining():
    nb = query_neighborhood("whisky tasting")
    cursor = nb.get("cursor") or ""
    assert "food.dining" not in cursor
    assert _unindexed(nb) or "dining" not in cursor


def test_sourdough_discard_recipes_prefers_fermentation():
    nb = query_neighborhood("sourdough discard recipes")
    cursor = nb.get("cursor") or ""
    blob = (
        cursor
        + " "
        + " ".join(b["id"] for b in nb["breadcrumb"])
        + " "
        + _titles(nb["ideas"] + nb["refine"] + nb["expand"])
        + " "
        + " ".join(_ids(nb["ideas"]))
    )
    assert "fermentation" in blob or "bake" in blob or "discard" in blob
    assert cursor != "food.cooking"
    assert "recipe_lab" not in cursor
    ideas = _titles(nb["ideas"])
    assert "recipe lab" not in ideas or "bake" in ideas or "sourdough" in ideas or "discard" in ideas
