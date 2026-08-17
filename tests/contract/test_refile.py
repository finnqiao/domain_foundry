"""Unfiled entries can be repaired through scoped routing and apply."""

from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.routing.router import Router
from domain_foundry_core.security.store import connect_ro


def _ready(workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.packs.reload()
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    return api


def test_refile_unfiled_entry_and_idempotency(workspace):
    api = _ready(workspace)
    capture = api.capture("zzz unrelated administrative chatter", channel="web")
    assert capture.status == "unfiled"

    before = len(api.block_data.export_rows("sourdough", "bake"))
    result = api.refile_entry(capture.entry_id, "sourdough")
    assert result["applied"] is True
    assert result["domain"] == "sourdough"
    assert len(api.block_data.export_rows("sourdough", "bake")) == before + 1

    row = api.block_data.export_rows("sourdough", "bake")[-1]
    assert row["entry_id"] == capture.entry_id
    conn = connect_ro(workspace.ledger_db)
    try:
        card = conn.execute(
            "SELECT status FROM unfiled_card WHERE entry_id = ?",
            (capture.entry_id,),
        ).fetchone()
    finally:
        conn.close()
    assert card["status"] == "filed"

    replay = api.refile_entry(capture.entry_id, "sourdough")
    assert replay["idempotent_replay"] is True
    assert len(api.block_data.export_rows("sourdough", "bake")) == before + 1


def test_refile_unknown_pack_and_http_validation(workspace):
    api = _ready(workspace)
    capture = api.capture("zzz another unrelated note", channel="web")
    result = api.refile_entry(capture.entry_id, "nope")
    assert result["applied"] is False
    assert "not installed" in result["error"]

    client = TestClient(create_app(workspace.home, enable_drain_loop=False))
    missing_domain = client.post(f"/api/entries/{capture.entry_id}/refile", json={})
    assert missing_domain.status_code == 422
    response = client.post(
        f"/api/entries/{capture.entry_id}/refile",
        json={"domain": "sourdough"},
    )
    assert response.status_code == 200
    assert response.json()["applied"] is True
