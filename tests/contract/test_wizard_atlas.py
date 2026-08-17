"""Held-out idea-atlas neighborhood evals (plan §7). No live LLM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import land_wizard

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.atlas.loader import load_atlas
from domain_foundry_core.atlas.query import query_neighborhood
from domain_foundry_core.wizard.jobs import compile_jobs, shortlist_for_ideas

SUITE = Path("examples/heldout/wizard_atlas_suite.jsonl")


def _load_suite() -> list[dict]:
    rows = []
    for line in SUITE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _blob(nb: dict) -> str:
    parts = [nb.get("cursor") or ""]
    for key in ("refine", "expand", "ideas", "breadcrumb"):
        for card in nb.get(key) or []:
            parts.append(card.get("id") or "")
            parts.append(card.get("title") or "")
            parts.append(card.get("pitch") or "")
    return " ".join(parts).lower()


@pytest.mark.parametrize("case", _load_suite(), ids=lambda c: c["id"])
def test_atlas_suite_neighborhoods(case):
    nb = query_neighborhood(case["goal"])
    blob = _blob(nb)
    for needle in case.get("expect_refine") or []:
        assert needle.lower() in blob, (case["id"], needle, blob)
    for needle in case.get("expect_ideas") or []:
        assert needle.lower() in blob, (case["id"], needle, blob)
    if case.get("expect_idea_mix"):
        provenances = {i.get("provenance") for i in nb.get("ideas") or []}
        assert provenances & {"world", "both"}
        assert provenances & {"foundry", "both"}
    if case.get("expect_world_analog"):
        assert any(i.get("world_analogs") for i in nb.get("ideas") or [])
    if case.get("expect_highlight"):
        highlighted = [i for i in nb.get("ideas") or [] if i.get("highlighted")]
        assert highlighted
        titles = " ".join(i["title"].lower() for i in highlighted)
        for needle in case["expect_highlight"]:
            assert needle.lower() in titles
    if case.get("expect_expand"):
        expand = _blob({"ideas": nb.get("ideas") or [], "expand": nb.get("expand") or [], "refine": nb.get("refine") or []})
        assert any(n.lower() in expand for n in case["expect_expand"])
    if case.get("not_generic_workout"):
        ideas = " ".join(i.get("title") or "" for i in nb.get("ideas") or []).lower()
        assert "training" in ideas or "pickup" in ideas or "tactical" in ideas
    if case.get("forbid_only_meal_log"):
        titles = [i.get("title", "").lower() for i in nb.get("ideas") or []]
        assert any("recipe" in t or "nutrition" in t or "map" in t or "dining" in t for t in titles)


def test_atlas_suite_no_key_path_still_returns_shipped_neighborhood():
    nb = query_neighborhood("diving")
    assert nb.get("unindexed") is not True
    assert nb.get("ideas")


def test_pokedex_compile_contract_from_suite_jobs(tmp_path):
    graph = load_atlas()
    idea = graph.get("diving.marine_naturalism.species_pokedex")
    assert idea is not None
    blueprint = compile_jobs(
        shortlist_for_ideas([idea], goal="remember the animals"),
        goal="remember the animals",
        jobs=list(idea.jobs),
        domain_hint="species",
    )
    assert len(blueprint["objects"]) >= 2
    blocks = {v["block"] for v in blueprint["views"]}
    assert "gallery" in blocks and "map" in blocks
    assert any(obj.get("links") for obj in blueprint["objects"].values())


def test_recipe_lab_compiles_instead_of_kitchen_sink(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("food")
    turn = api.wizard_reply(fork["session_id"], "recipe lab")
    assert turn["state"] in {"test_drive", "repair"}
    name = (turn.get("pack") or {}).get("name") or turn.get("domain")
    assert name == "recipes"
    pack = api.packs.get("recipes")
    assert pack is not None
    assert pack.manifest.title != "Food Lab"


def test_wizard_lands_food_and_diving_from_atlas(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    food = api.new_domain("food")
    assert food["state"] == "fork"
    assert food["neighborhood"]["ideas"]
    diving = land_wizard(api, "scuba", reply="dive log")
    assert diving["state"] == "test_drive"
    pack = api.packs.get(diving["pack"]["name"])
    assert pack is not None
    assert len(pack.objects) >= 1
