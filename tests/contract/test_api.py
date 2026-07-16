from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domain_expert_core.api.app import create_app, run_server
from domain_expert_core.api.harness import HarnessAPI


def test_fastapi_capture_query_health(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_EXPERT_HOME", str(workspace.home))
    HarnessAPI(workspace.home).init()
    client = TestClient(create_app(workspace.home))

    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = client.post(
        "/api/capture",
        json={"text": "api capture synthetic", "channel": "web", "source_ref": "w1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ledger_only"
    entry_id = body["entry_id"]

    r = client.get("/api/query", params={"status": "ledger_only"})
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert any(row["id"] == entry_id for row in rows)


def test_non_local_bind_requires_token(tmp_path: Path):
    with pytest.raises(SystemExit):
        run_server(tmp_path / "h", host="0.0.0.0", port=8799, api_token=None)
