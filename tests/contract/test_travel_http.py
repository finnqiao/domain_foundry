"""HTTP and harness contracts for policy-gated travel UI actions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.security.store import connect_ro

TOKEN = "travel-secret"


def _ready(home: Path) -> HarnessAPI:
    api = HarnessAPI(home)
    api.init()
    api.packs.activate_bundled("travel")
    return api


def _client(home: Path) -> TestClient:
    _ready(home)
    return TestClient(create_app(home, api_token=TOKEN, enable_drain_loop=False))


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_declared_ui_action_delegates_with_web_provenance(monkeypatch, tmp_path: Path):
    api = _ready(tmp_path / "home")
    delegated = Mock(return_value={"ok": True, "operation": "update"})
    monkeypatch.setattr(api, "apply_operation", delegated)

    result = api.apply_ui_action(
        domain="travel",
        operation="update",
        object_type="packing_item",
        fields={"packed": True},
        object_uid="travel:packing_item:test",
    )

    assert result["ok"] is True
    delegated.assert_called_once_with(
        domain="travel",
        operation="update",
        object_type="packing_item",
        fields={"packed": True},
        object_uid="travel:packing_item:test",
        entry_id=None,
        channel="web",
        actor="web-ui",
    )


def test_apply_http_requires_auth_and_declared_action_leaves_provenance(tmp_path: Path):
    home = tmp_path / "home"
    client = _client(home)
    api = client.app.state.harness  # type: ignore[attr-defined]

    created = api.apply_operation(
        domain="travel",
        operation="create",
        object_type="packing_item",
        fields={"name": "Passport", "category": "documents", "packed": False},
    )
    uid = created["object_uid"]
    assert uid

    assert client.post(
        "/api/apply",
        json={
            "domain": "travel",
            "operation": "update",
            "object_type": "packing_item",
            "object_uid": uid,
            "fields": {"packed": True},
        },
    ).status_code == 401

    applied = client.post(
        "/api/apply",
        json={
            "domain": "travel",
            "operation": "update",
            "object_type": "packing_item",
            "object_uid": uid,
            "fields": {"packed": True},
        },
        headers=_auth(),
    )
    assert applied.status_code == 200
    assert applied.json()["ok"] is True

    conn = connect_ro(api.workspace.ledger_db)
    try:
        provenance = conn.execute(
            "SELECT actor, actor_channel FROM object_revision "
            "WHERE object_uid = ? ORDER BY revision DESC LIMIT 1",
            (uid,),
        ).fetchone()
    finally:
        conn.close()
    assert provenance["actor"] == "web-ui"
    assert provenance["actor_channel"] == "web"


def test_apply_http_rejects_undeclared_fields_and_operations(tmp_path: Path):
    home = tmp_path / "home"
    client = _client(home)
    body = {
        "domain": "travel",
        "operation": "update",
        "object_type": "packing_item",
        "object_uid": "travel:packing_item:missing",
        "fields": {"packed": True, "notes": "should be refused"},
    }
    extra_field = client.post("/api/apply", json=body, headers=_auth())
    assert extra_field.status_code == 403
    assert "not available" in extra_field.json()["detail"]

    undeclared_operation = client.post(
        "/api/apply",
        json={**body, "operation": "delete", "fields": {}},
        headers=_auth(),
    )
    assert undeclared_operation.status_code == 403
    assert "not available" in undeclared_operation.json()["detail"]
