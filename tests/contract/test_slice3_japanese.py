"""Slice 3 Japanese import/session shell contracts."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.security.store import connect_ro

REPO = Path(__file__).resolve().parents[2]


def _client(workspace) -> tuple[HarnessAPI, TestClient]:
    HarnessAPI(workspace.home).init()
    app = create_app(workspace.home, enable_drain_loop=False)
    return app.state.harness, TestClient(app)


def test_japanese_pack_import_preview_commit_is_reconcilable(workspace):
    api, client = _client(workspace)
    assert client.post("/api/packs/activate", json={"name": "japanese"}).status_code == 200
    source = REPO / "packs" / "japanese" / "evals" / "import_fixture"
    body = {
        "domain": "japanese",
        "mapping_id": "japanese_cards",
        "source_path": str(source),
    }

    preview = client.post("/api/import/pack/preview", json=body)
    assert preview.status_code == 200, preview.text
    preview_payload = preview.json()
    assert preview_payload["phase"] == "preview"
    assert preview_payload["would_import"] == 4
    assert preview_payload["complete"] is True
    assert preview_payload["preview_token"]

    committed = client.post(
        "/api/import/pack/commit",
        json={**body, "preview_token": preview_payload["preview_token"]},
    )
    assert committed.status_code == 200, committed.text
    committed_payload = committed.json()
    assert committed_payload["imported"] == 4
    assert committed_payload["failed"] == 0
    assert committed_payload["complete"] is True

    # Source refs and original timestamps remain visible in the ledger; the
    # import does not become an opaque bulk insert.
    conn = connect_ro(workspace.ledger_db)
    try:
        row = conn.execute(
            "SELECT source_ref, captured_at, channel FROM capture_event WHERE source_ref = ?",
            ("japanese:cards:jp_vocab:jp_card_001",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["channel"] == "japanese-card-import"
    assert row["captured_at"] == "2026-07-12T09:00:00+00:00"

    again_preview = client.post("/api/import/pack/preview", json=body).json()
    again = client.post(
        "/api/import/pack/commit",
        json={**body, "preview_token": again_preview["preview_token"]},
    )
    assert again.status_code == 200
    assert again.json()["imported"] == 0
    assert again.json()["skipped_existing"] == 4


def test_japanese_import_requires_preview_and_exposes_declaration(workspace):
    _api, client = _client(workspace)
    assert client.post("/api/packs/activate", json={"name": "japanese"}).status_code == 200
    mappings = client.get("/api/import/pack/japanese/mappings")
    assert mappings.status_code == 200
    assert mappings.json()["mappings"][0]["id"] == "japanese_cards"
    response = client.post(
        "/api/import/pack/commit",
        json={
            "domain": "japanese",
            "mapping_id": "japanese_cards",
            "preview_token": "not-a-preview",
        },
    )
    assert response.status_code == 409


def test_japanese_quiz_session_resumes_and_schedule_is_visible_and_pausable(workspace):
    api, client = _client(workspace)
    assert client.post("/api/packs/activate", json={"name": "japanese"}).status_code == 200
    seeded = api.apply_operation(
        domain="japanese",
        operation="create",
        object_type="jp_vocab",
        fields={"word": "水", "meaning": "water"},
        channel="test",
        actor="test",
    )
    assert seeded["ok"]

    started = client.post("/api/quiz/start", json={"domain": "japanese", "limit": 1})
    assert started.status_code == 200, started.text
    session = started.json()
    assert session["total"] == 1
    assert session["prompt"] == "水"

    resumed = client.get("/api/quiz/next", params={"domain": "japanese"})
    assert resumed.status_code == 200
    assert resumed.json()["session_id"] == session["session_id"]

    graded = client.post(
        "/api/quiz/grade",
        json={"domain": "japanese", "session_id": session["session_id"], "grade": "good"},
    )
    assert graded.status_code == 200
    assert graded.json()["done"] is True

    activity = client.get("/api/quiz/activity", params={"domain": "japanese"})
    assert activity.status_code == 200
    assert activity.json()["sessions"][0]["status"] == "completed"

    schedules = client.get("/api/schedules", params={"domain": "japanese"})
    assert schedules.status_code == 200
    schedule = schedules.json()["schedules"][0]
    assert schedule["timezone"] == "Pacific/Honolulu"
    assert schedule["missed_run_policy"] == "next_window"
    assert schedule["human_gate"] is True

    paused = client.post(
        f"/api/schedules/japanese/{schedule['id']}/status", json={"status": "paused"}
    )
    assert paused.status_code == 200
    assert api.evaluate_schedules(domain="japanese")[0]["skipped_reason"] == "paused"
    resumed_schedule = client.post(
        f"/api/schedules/japanese/{schedule['id']}/status", json={"status": "active"}
    )
    assert resumed_schedule.status_code == 200
