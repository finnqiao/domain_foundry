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
    if turn["state"] == "looks":
        turn = api.wizard_reply(fork["session_id"], "build it")
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


def test_sourdough_visualize_stays_and_looks_before_analog(workspace, monkeypatch, tmp_path):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("i have a log of sourdough bakes")
    assert fork["state"] == "fork"
    assert fork.get("pack") is None
    message = fork["message"].lower()
    assert "refine:" not in message
    assert "food →" not in message
    highlighted = [i for i in fork["neighborhood"]["ideas"] if i.get("highlighted")]
    titles = " ".join(i["title"].lower() for i in highlighted) or " ".join(
        i["title"].lower() for i in fork["neighborhood"]["ideas"]
    )
    assert "bake" in titles or "sourdough" in titles

    notes = tmp_path / "bakes"
    notes.mkdir()
    (notes / "notes.txt").write_text(
        "75% hydration country loaf, open crumb\n78% batard, sprang well\n",
        encoding="utf-8",
    )
    ingested = api.wizard_reply(fork["session_id"], str(notes))
    assert ingested["state"] == "fork"
    assert ingested.get("ingest", {}).get("files", 0) >= 1

    looks = api.wizard_reply(fork["session_id"], "i want to data visualize all my bakes")
    assert looks["state"] == "looks"
    assert looks.get("pack") is None
    ids = " ".join(L.get("idea_id") or "" for L in looks.get("looks") or [])
    assert "bake_lab" in ids
    html = " ".join(L.get("html") or "" for L in looks.get("looks") or []).lower()
    assert "scatter" in html or "chart" in html or "df-look-improvement" in html
    cursor = (looks.get("neighborhood") or {}).get("cursor") or ""
    assert "soccer" not in cursor

    crit = api.wizard_reply(fork["session_id"], "make it darker and denser")
    assert crit["state"] == "looks"
    rounds = [int(L.get("round") or 1) for L in crit.get("looks") or []]
    assert max(rounds) >= 2

    live = api.wizard_reply(fork["session_id"], "the scatter one")
    assert live["state"] in {"test_drive", "repair"}
    assert live["design_mode"] == "starter"
    assert live["pack"]["name"] == "sourdough"


def test_diving_pokedex_look_compiles_without_analog(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("I want to remember the animals I see underwater")
    assert fork["state"] == "fork"
    ideas = " ".join(i.get("title") or "" for i in fork["neighborhood"]["ideas"]).lower()
    assert "pokedex" in ideas or "species" in ideas
    looks = api.wizard_reply(fork["session_id"], "the field-guide look")
    assert looks["state"] == "looks"
    ids = " ".join(L.get("idea_id") or "" for L in looks.get("looks") or [])
    assert "pokedex" in ids or "species" in ids
    html = " ".join(L.get("html") or "" for L in looks.get("looks") or []).lower()
    assert "gallery" in html or "catalog" in html or "field" in html or "map" in html
    live = api.wizard_reply(fork["session_id"], "build it")
    assert live["state"] in {"test_drive", "repair"}
    assert live["design_mode"] != "starter"
    name = (live.get("pack") or {}).get("name") or live.get("domain")
    assert name and name != "sourdough"
    pack = api.packs.get(name)
    assert pack is not None
    views = (pack.projections.app or {}).get("views") or []
    blocks = {v.get("block") for v in views if isinstance(v, dict)}
    assert "gallery" in blocks or "map" in blocks


def test_pokemon_cards_offers_card_set_and_pull_then_files(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("i collect pokemon cards")
    assert fork["state"] == "fork"
    assert fork.get("pack") is None
    ideas = " ".join(i.get("title") or "" for i in fork["neighborhood"]["ideas"]).lower()
    assert "card" in ideas
    assert "set" in ideas or "pull" in ideas
    highlighted = [i for i in fork["neighborhood"]["ideas"] if i.get("highlighted")]
    titles = " ".join(i["title"].lower() for i in highlighted) or ideas
    assert "card" in titles
    cursor = (fork.get("neighborhood") or {}).get("cursor") or ""
    assert "diving" not in cursor
    assert "pokedex" not in titles

    looks = api.wizard_reply(fork["session_id"], "a dex of the cards i own with photos")
    assert looks["state"] == "looks"
    ids = " ".join(L.get("idea_id") or "" for L in looks.get("looks") or [])
    assert "card_dex" in ids
    html = " ".join(L.get("html") or "" for L in looks.get("looks") or []).lower()
    assert "gallery" in html
    assert "repeat(3" in html

    # Asking in words no longer restyles the look by guessing at keywords like
    # "denser" (Lane C, C5). The look still comes back and stays a gallery; how
    # much room it gives each thing is now a control on the review page, and it
    # reaches the build through `look --read`.
    crit = api.wizard_reply(fork["session_id"], "make the gallery denser")
    assert crit["state"] == "looks"
    crit_html = " ".join(L.get("html") or "" for L in crit.get("looks") or []).lower()
    assert "gallery" in crit_html

    live = api.wizard_reply(fork["session_id"], "build it")
    assert live["state"] in {"test_drive", "repair"}
    name = (live.get("pack") or {}).get("name") or live.get("domain")
    assert name
    pack = api.packs.get(name)
    assert pack is not None
    assert "card" in pack.objects
    views = (pack.projections.app or {}).get("views") or []
    blocks = {v.get("block") for v in views if isinstance(v, dict)}
    assert "gallery" in blocks

    cap = api.wizard_reply(
        live["session_id"],
        "pulled a holographic Charizard from a 151 booster, NM",
    )
    routed = (cap.get("capture") or {}).get("routed") or []
    assert routed, cap
    assert routed[0]["domain"] == name
    assert routed[0]["object_type"] == "card"
    assert routed[0].get("disposition") not in {"unfiled", "ledger_only"}

    idle = api.capture("nice afternoon, weather was good")
    idle_data = idle.model_dump()
    idle_routed = idle_data.get("routed") or []
    assert idle_data.get("status") in {"unfiled", "ledger_only"} or not any(
        s.get("domain") == name and s.get("disposition") not in {"unfiled", "ledger_only"}
        for s in idle_routed
    ), idle_data

    corr = api.correct(text="that Charizard was LP not NM")
    assert corr.get("applied") is True, corr
    patched = (corr.get("details") or {}).get("fields") or {}
    assert "charizard" not in {k.lower() for k in patched}
    assert "notes" in patched or "condition" in patched, patched
    assert any(str(v).upper() == "LP" for v in patched.values()), patched


def _force_unindexed(monkeypatch):
    """Simulate the sibling query.py miss: unknown goals, empty ideas."""

    def fake_neighborhood(goal, overlay=None, cursor_id=None):
        return {
            "cursor": None,
            "breadcrumb": [],
            "refine": [],
            "expand": [],
            "ideas": [],
            "simple_log": True,
            "unindexed": True,
        }

    monkeypatch.setattr(
        "domain_foundry_core.wizard.engine.query_neighborhood",
        fake_neighborhood,
    )


def test_unindexed_invents_three_job_shaped_ideas(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    _force_unindexed(monkeypatch)
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("track my lego builds")
    assert fork["state"] == "fork"
    ideas = (fork.get("neighborhood") or {}).get("ideas") or []
    assert len(ideas) == 3
    titles = " ".join(i.get("title") or "" for i in ideas).lower()
    ids = " ".join(i.get("id") or "" for i in ideas)
    assert "lego" in titles
    assert "shelf" in titles and "timeline" in titles and "chart" in titles
    assert "invented.lego.shelf" in ids
    assert all((i.get("id") or "").startswith("invented.") for i in ideas)
    assert all(i.get("jobs") for i in ideas)
    assert any(
        "catalog" in (i.get("jobs") or []) and "media_dex" in (i.get("jobs") or [])
        for i in ideas
    )
    assert any("event_log" in (i.get("jobs") or []) for i in ideas)
    assert any("improvement" in (i.get("jobs") or []) for i in ideas)
    cursor = (fork.get("neighborhood") or {}).get("cursor") or ""
    assert "wildlife" not in cursor
    assert "wildlife" not in titles


def test_invented_shelf_compiles_not_sourdough_analog(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    _force_unindexed(monkeypatch)
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("track my lego builds")
    looks = api.wizard_reply(fork["session_id"], "1")
    assert looks["state"] == "looks"
    ids = " ".join(L.get("idea_id") or "" for L in looks.get("looks") or [])
    assert "invented.lego.shelf" in ids
    live = api.wizard_reply(fork["session_id"], "build it")
    # An invented card is named after the goal's first keyword and knows no
    # domain words, so the wizard asks for two before it designs (ADR-010).
    assert live["state"] == "elicit"
    live = api.wizard_reply(fork["session_id"], "built the Hogwarts Castle set, 6020 pieces")
    assert live["state"] == "elicit"
    live = api.wizard_reply(fork["session_id"], "sorted the loose bricks into the parts bins")
    assert live["state"] in {"test_drive", "repair"}
    assert live["design_mode"] != "starter"
    name = (live.get("pack") or {}).get("name") or live.get("domain")
    assert name and name != "sourdough"
    pack = api.packs.get(name)
    assert pack is not None
    views = (pack.projections.app or {}).get("views") or []
    blocks = {v.get("block") for v in views if isinstance(v, dict)}
    assert "gallery" in blocks


def test_analog_without_hero_view_compiles_instead_of_starter(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("a photo dex of my plants")
    ideas = (fork.get("neighborhood") or {}).get("ideas") or []
    collection = next(
        (
            i
            for i in ideas
            if i.get("analog_pack") == "plants" and "media_dex" in (i.get("jobs") or [])
        ),
        None,
    )
    assert collection is not None, [i.get("id") for i in ideas]
    looks = api.wizard_reply(fork["session_id"], collection["title"])
    assert looks["state"] == "looks"
    heroes = [L.get("hero_job") for L in looks.get("looks") or []]
    assert "media_dex" in heroes
    live = api.wizard_reply(fork["session_id"], "build it")
    assert live["state"] in {"test_drive", "repair"}
    assert live["design_mode"] != "starter"
    name = (live.get("pack") or {}).get("name") or live.get("domain")
    assert name and name != "plants"
    pack = api.packs.get(name)
    assert pack is not None
    views = (pack.projections.app or {}).get("views") or []
    blocks = {v.get("block") for v in views if isinstance(v, dict)}
    assert "gallery" in blocks


def test_unindexed_goals_do_not_land_on_wildlife():
    for goal in ("xyzzy plugh foobar", "track my lego builds", "warhammer painting"):
        nb = query_neighborhood(goal)
        assert nb.get("unindexed") is True or not nb.get("cursor"), (goal, nb.get("cursor"))
        assert "wildlife" not in (nb.get("cursor") or "")
        assert "animals.wildlife" != nb.get("cursor")


def test_birdwatching_neighborhood_is_wildlife():
    nb = query_neighborhood("birdwatching")
    blob = _blob(nb)
    assert "wildlife" in blob
    assert nb.get("unindexed") is not True


def test_whisky_tasting_neighborhood_is_drinks_not_dining():
    """Whisky is a drinks shelf, not a restaurant.

    This used to assert "dining" appeared nowhere in the whole neighbourhood
    blob, which was safe only while whisky was unindexed. Now that the atlas
    carries ``food.drinks``, ``food.dining`` shows up in the blob as an
    *adjacent sibling chip* — both are practices under the ``food`` bucket, so
    every food neighbourhood offers the others as expand options. That chip is
    correct behaviour, not a mis-landing, so the assertion is tightened to the
    two things that actually encode the intent: the cursor, and the ideas the
    fork offers.
    """
    nb = query_neighborhood("whisky tasting")
    cursor = nb.get("cursor") or ""
    assert cursor.startswith("food.drinks"), cursor
    assert "food.dining" not in cursor
    idea_ids = [i.get("id", "") for i in nb.get("ideas") or []]
    assert idea_ids, nb
    assert not any(i.startswith("food.dining") for i in idea_ids), idea_ids


def test_sourdough_discard_recipes_neighborhood_is_fermentation():
    nb = query_neighborhood("sourdough discard recipes")
    blob = _blob(nb)
    cursor = nb.get("cursor") or ""
    assert "fermentation" in blob or "bake" in blob or "discard" in blob
    assert cursor != "food.cooking"
    assert "food.cooking.recipe_lab" not in cursor


def test_wizard_unindexed_goal_stays_off_wildlife(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("track my lego builds")
    nb = fork.get("neighborhood") or {}
    assert nb.get("unindexed") is True or not nb.get("cursor")
    assert "wildlife" not in (nb.get("cursor") or "")


def test_wizard_birdwatching_offers_wildlife(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("birdwatching")
    nb = fork.get("neighborhood") or {}
    blob = _blob(nb)
    assert "wildlife" in blob
    assert "diving" not in (nb.get("cursor") or "")


def test_wizard_whisky_tasting_not_dining(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("whisky tasting")
    nb = fork.get("neighborhood") or {}
    assert "food.dining" not in (nb.get("cursor") or "")


def test_wizard_sourdough_discard_recipes_not_only_recipe_lab(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("sourdough discard recipes")
    nb = fork.get("neighborhood") or {}
    blob = _blob(nb)
    cursor = nb.get("cursor") or ""
    assert "fermentation" in blob or "bake" in blob or "discard" in blob
    assert cursor != "food.cooking"
    titles = " ".join(i.get("title") or "" for i in nb.get("ideas") or []).lower()
    assert "bake" in titles or "sourdough" in titles or "starter" in titles or "discard" in titles
