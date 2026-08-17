"""Co-build neighbor suggestions + hardening add_object / add_capability."""

from __future__ import annotations

from tests.conftest import land_wizard

from domain_foundry_core.api.harness import HarnessAPI


def test_animal_residue_on_dive_log_suggests_pokedex(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    turn = land_wizard(api, "scuba", reply="dive log")
    domain = turn["pack"]["name"]
    for text in (
        "45 min at Blue Hole, turtle at 18m",
        "spotted a frogfish on the wreck, 22m",
        "nudibranch on the wall, got a photo",
        "another turtle at the same site, 18m",
    ):
        api.capture(text)
    suggestion = api.wizard_suggest(domain)
    assert suggestion is not None
    blob = json_blob(suggestion)
    assert "pokedex" in blob or "species" in blob or "naturalism" in blob


def json_blob(value) -> str:
    import json

    return json.dumps(value).lower()


def test_hardening_add_object_and_capability(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    api.activate_pack("plants")
    preview = api.hardening_preview("plants", "add a species object")
    assert "species" in (preview["plan"].get("added_objects") or [])
    applied = api.hardening_apply("plants", "add a species object")
    assert applied["applied"] is True
    pack = api.packs.get("plants")
    assert pack is not None
    assert "species" in pack.objects

    cap = api.hardening_apply("plants", "add a media capability")
    assert cap["applied"] is True
    pack = api.packs.get("plants")
    assert pack is not None
    assert pack.capabilities.get("media")


def test_inspect_pack_and_atlas_search(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    api.activate_pack("plants")
    inspected = api.inspect_pack("plants")
    assert "schema.yaml" in inspected["files"]
    nb = api.atlas_search("diving")
    assert nb["ideas"]
    report = api.atlas_validate()
    assert report["errors"] == []


def test_show_schema_before_activate(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain("diving")
    preview = api.wizard_reply(fork["session_id"], "show schema")
    assert preview["state"] == "schema_preview"
    assert preview.get("schema_preview")
    back = api.wizard_reply(fork["session_id"], "back")
    assert back["state"] == "fork"
