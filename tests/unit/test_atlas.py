"""Idea atlas seed + neighborhood query."""

from __future__ import annotations

from pathlib import Path

from domain_foundry_core.atlas.loader import load_atlas, validate_atlas, graph_stats
from domain_foundry_core.atlas.query import query_neighborhood


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
    assert graph.get("food") is not None
    assert graph.get("food").title == "Food (overlay)"
