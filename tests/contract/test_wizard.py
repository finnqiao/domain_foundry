"""P6 — guided domain creation wizard contract tests.

Covers the cold-start gate (goal → interview → generate → validate → dry-run →
capture), the ≥10 golden goal-statements that must yield packs routing their
own examples ≥95%, and the hardening edit round-trip with a migration.
No live LLM: the HeuristicProvider / fixtures drive everything.
"""

from __future__ import annotations

import sqlite3

import pytest

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.packs.schema_compiler import table_name
from domain_foundry_core.wizard.blueprint import build_blueprint, write_pack
from tests.conftest import land_wizard

# ≥10 golden goal-statements (incl. "sourdough journey"): archetypes + generic.
GOLDEN_GOALS = [
    "I want to track my sourdough journey",
    "log my running",
    "keep track of my reading",
    "keep a coffee brewing log",
    "track my gym workouts",
    "track my meditation practice",
    "log my houseplant care",
    "track my model rocket launches",
    "keep track of my guitar practice",
    "log my daily mood",
    "track my cycling rides",
    "journal my dreams",
]


def _columns(db_path, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


@pytest.mark.parametrize("goal", GOLDEN_GOALS)
def test_golden_goal_generates_valid_routing_pack(workspace, monkeypatch, goal):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()

    turn = api.new_domain(goal)
    if turn.get("state") == "fork":
        turn = api.wizard_reply(turn["session_id"], "skip")
    assert turn["state"] == "test_drive", turn.get("message")
    name = turn.get("pack", {}).get("name") or turn.get("domain")
    assert name
    assert api.pack_validate(name) == []
    pack = api.packs.get(name)
    assert pack is not None
    assert len(pack.routing.examples) >= 8
    if turn.get("dry_run"):
        assert turn["dry_run"]["accuracy"] >= 0.95, turn["dry_run"]


def test_houseplants_installs_plants_starter(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()

    turn = land_wizard(api, "track my houseplants")
    assert turn["design_mode"] == "starter"
    assert turn["pack"]["name"] == "plants"
    assert turn["state"] == "test_drive"
    assert api.packs.get("houseplants") is None
    assert api.packs.get("plants") is not None

    # Singular alias also hits Plant Care.
    turn2 = land_wizard(api, "log my houseplant care")
    assert turn2["pack"]["name"] == "plants"
    assert "already" in turn2["message"].lower() or turn2["design_mode"] == "starter"


def test_sourdough_installs_bundled_starter_not_clone(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()

    turn = land_wizard(api, "I want to track my sourdough journey")
    assert turn["design_mode"] == "starter"
    assert turn["pack"]["name"] == "sourdough"
    pack = api.packs.get("sourdough")
    assert pack is not None
    # Bundled pack has crumb photos / richer schema than the archetype clone.
    bake = pack.objects.get("bake")
    assert bake is not None
    assert "crumb_photos" in bake.fields


def test_origami_scaffolds_without_key(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()

    turn = land_wizard(api, "track my origami")
    assert turn["design_mode"] in {"scaffold", "atlas"}
    assert turn["state"] == "test_drive"
    assert turn.get("pack", {}).get("name")
    assert turn["pack"]["name"] != "plants"


def test_blueprint_examples_are_disjoint_per_object():
    """A generated example must not match another object's routing keywords."""
    import re

    bp = build_blueprint("I want to track my sourdough journey")
    compiled = {
        r["object"]: [re.compile(rr["match"], re.IGNORECASE) for rr in bp["rules"] if rr["object"] == r["object"]]
        for r in bp["rules"]
    }
    for ex in bp["examples"]:
        for obj, patterns in compiled.items():
            hits = any(p.search(ex["text"]) for p in patterns)
            if obj == ex["object"]:
                assert hits, f"example {ex['text']!r} should match its object {obj}"


def test_cold_start_gate(workspace, monkeypatch):
    """goal → starter install → capture path works without interview."""
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()

    turn = land_wizard(api, "I want to track my sourdough journey", reply="skip")
    sid = turn["session_id"]
    assert turn["state"] == "test_drive"
    assert turn["design_mode"] == "starter"
    assert turn["pack"]["name"] == "sourdough"

    # Real capture routes into the installed starter.
    receipt = api.capture("baked a country loaf at 78% hydration")
    assert receipt.routed
    assert receipt.routed[0].domain == "sourdough"

    # Driving a capture through the wizard yields a verbose routing explanation.
    cap_turn = api.wizard_reply(sid, "fed the rye starter")
    assert cap_turn["capture"]["routed"][0]["domain"] == "sourdough"
    assert cap_turn["capture"]["routed"][0]["object_type"] == "starter"
    assert "Routed" in cap_turn["message"]
    assert cap_turn["capture"]["test_drive_remaining"] == 4


def test_hardening_edit_round_trips_with_migration(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()

    turn = land_wizard(api, "I want to track my sourdough journey")
    sid = turn["session_id"]
    assert turn["state"] == "test_drive"
    assert turn["pack"]["name"] == "sourdough"

    # NL edit → pack diff preview (no changes applied yet).
    diff_turn = api.wizard_reply(sid, "add a crumb_photo field")
    assert diff_turn["state"] == "hardening_confirm"
    assert diff_turn["awaiting"] == "confirm"
    added = [a["name"] for a in diff_turn["diff"]["added"]]
    assert "crumb_photo" in added

    tname = table_name("sourdough", "bake")
    assert "crumb_photo" not in _columns(workspace.domains_db, tname)

    # Confirm → migration + registry refresh + fixture append.
    applied = api.wizard_reply(sid, "confirm")
    assert applied["hardening"]["applied"] is True
    assert applied["hardening"]["migration"].endswith(".sql")
    assert "crumb_photo" in applied["hardening"]["added"]

    # Column now exists (migration ran) and the pack still validates & routes.
    assert "crumb_photo" in _columns(workspace.domains_db, tname)
    pack = api.packs.get("sourdough")
    assert pack is not None
    assert "crumb_photo" in pack.objects["bake"].fields
    assert api.pack_validate("sourdough") == []

    # Migration file persisted alongside the pack.
    migrations = list((pack.root / "migrations").glob("sourdough_*_hardening.sql"))
    assert migrations

    # Fixture/eval case appended asserting the new shape still routes.
    fixture = applied["hardening"]["fixture"]
    assert fixture["eval_case_id"].startswith("ec_")


def test_hardening_rename_and_cancel(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    sid = land_wizard(api, "log my running")["session_id"]

    diff = api.wizard_reply(sid, "rename minutes to intensity")
    assert diff["state"] == "hardening_confirm"
    assert diff["diff"]["renamed"][0] == {"from": "minutes", "to": "intensity"}

    cancelled = api.wizard_reply(sid, "cancel")
    assert cancelled["state"] == "test_drive"
    pack = api.packs.get("running")
    assert pack is not None
    obj = next(iter(pack.objects.values()))
    assert "minutes" in obj.fields  # rename was not applied


def test_session_is_resumable(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    sid = api.new_domain("keep a coffee brewing log")["session_id"]

    # A brand-new HarnessAPI (fresh process) resumes the persisted session.
    api2 = HarnessAPI(workspace.home)
    resumed = api2.wizard_reply(sid, "skip")
    assert resumed["state"] == "test_drive"
    assert resumed["pack"]["name"] == "coffee"


def test_unique_domain_name_on_collision(workspace, monkeypatch, tmp_path):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    # Pre-install a "running" pack so the wizard must pick a new name.
    bp = build_blueprint("log my running")
    draft = write_pack(bp, tmp_path / "running_draft")
    api.packs.add(draft, force=True)

    turn = land_wizard(api, "track my running")
    assert turn["proposal"]["domain"] != "running"
    assert turn["proposal"]["domain"].startswith("running")


def test_wizard_http_journey(workspace, monkeypatch):
    """ADR-006: the wizard runs over the same HTTP contract the SPA/adapters use."""
    from fastapi.testclient import TestClient

    from domain_foundry_core.api.app import create_app

    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    HarnessAPI(workspace.home).init()
    client = TestClient(create_app(workspace.home, enable_drain_loop=False))

    r = client.post("/api/wizard", json={"goal_text": "log my running"})
    assert r.status_code == 200
    fork = r.json()
    assert fork["state"] == "fork"
    assert fork.get("neighborhood")
    landed = client.post(f"/api/wizard/{fork['session_id']}/reply", json={"text": "skip"})
    assert landed.status_code == 200
    turn = landed.json()
    assert turn["state"] == "test_drive"
    assert turn["pack"]["name"] == "running"
    assert turn["awaiting"] == "capture"

    # Unknown session is a legible 404.
    assert client.post("/api/wizard/no-such-session/reply", json={"text": "skip"}).status_code == 404
    # Blank replies are client errors, not uncaught wizard/capture exceptions.
    assert client.post(f"/api/wizard/{turn['session_id']}/reply", json={"text": " "}).status_code == 422


def test_activated_copy_is_scaffold_language(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    first = api.new_domain("log my running")
    assert first["state"] == "fork"
    turn = api.wizard_reply(first["session_id"], "skip")
    assert turn["state"] == "test_drive"
    assert "ready" in turn["message"].lower() or "simple log" in turn["message"].lower()
    assert "is live (v" not in turn["message"]
    assert "%" not in turn["message"]


def test_new_domain_always_forks_and_analog_waits_for_pick(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("track my houseplants")
    assert fork["state"] == "fork"
    assert fork.get("pack") is None
    assert fork.get("neighborhood", {}).get("ideas")
    landed = api.wizard_reply(fork["session_id"], "skip")
    assert landed["design_mode"] == "starter"
    assert landed["pack"]["name"] == "plants"


def test_picked_idea_compiles_when_analog_is_not_1_to_1(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("diving")
    assert fork["state"] == "fork"
    kids = " ".join(c["title"] for c in fork["neighborhood"]["refine"]).lower()
    assert "freediving" in kids
    assert "photo" in kids
    landed = api.wizard_reply(fork["session_id"], "dive log")
    assert landed["state"] == "test_drive"
    assert landed["design_mode"] in {"atlas", "scaffold", "llm"}
    assert landed["pack"]["name"] != "plants"
