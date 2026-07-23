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
    assert turn["state"] == "interview"
    assert turn["proposal"]["domain"]
    assert len(turn["questions"]) <= 6

    done = api.wizard_reply(turn["session_id"], "skip")
    assert done["state"] == "test_drive", done.get("message")
    assert done["dry_run"]["accuracy"] >= 0.95, done["dry_run"]

    # Pack is installed and passes full validation.
    name = done["pack"]["name"]
    assert api.pack_validate(name) == []
    pack = api.packs.get(name)
    assert pack is not None
    assert len(pack.routing.examples) >= 8


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
    """goal → interview → generate → validate → dry-run → capture path works."""
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()

    turn = api.new_domain("I want to track my sourdough journey", test_drive=5)
    sid = turn["session_id"]
    assert turn["awaiting"] == "answers"

    activated = api.wizard_reply(sid, "skip")
    assert activated["state"] == "test_drive"
    assert activated["pack"]["name"] == "sourdough"
    assert activated["dry_run"]["accuracy"] >= 0.95

    # Real capture routes into the freshly generated domain.
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

    turn = api.new_domain("I want to track my sourdough journey")
    sid = turn["session_id"]
    api.wizard_reply(sid, "skip")

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
    sid = api.new_domain("log my running")["session_id"]
    api.wizard_reply(sid, "skip")

    diff = api.wizard_reply(sid, "rename effort to intensity")
    assert diff["state"] == "hardening_confirm"
    assert diff["diff"]["renamed"][0] == {"from": "effort", "to": "intensity"}

    cancelled = api.wizard_reply(sid, "cancel")
    assert cancelled["state"] == "test_drive"
    pack = api.packs.get("running")
    assert "effort" in pack.objects["run"].fields  # rename was not applied


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

    turn = api.new_domain("track my running")
    assert turn["proposal"]["domain"] != "running"
    assert turn["proposal"]["domain"].startswith("running")


def test_wizard_http_endpoints_are_gone(workspace, monkeypatch):
    """Mesh P0: wizard writes moved in-process; HTTP surface returns 410."""
    from fastapi.testclient import TestClient

    from domain_foundry_core.api.app import create_app

    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    client = TestClient(create_app(workspace.home, enable_drain_loop=False))

    assert client.post("/api/wizard", json={"goal_text": "log my running"}).status_code == 410
    assert client.post("/api/wizard/sess/reply", json={"text": "skip"}).status_code == 410

    # The same flow works through the embedded harness.
    body = api.new_domain("log my running")
    assert body["state"] == "interview"
    done = api.wizard_reply(body["session_id"], "skip")
    assert done["state"] == "test_drive"
    assert done["pack"]["name"] == "running"
