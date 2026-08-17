from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app, run_server
from domain_foundry_core.api.harness import HarnessAPI


def test_fastapi_serves_reads_and_writes(workspace, monkeypatch):
    """ADR-006: one daemon serves the read AND write contract."""
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    HarnessAPI(workspace.home).init()
    client = TestClient(create_app(workspace.home))

    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # HTTP write lands in the ledger and is visible through HTTP reads.
    r = client.post(
        "/api/capture",
        json={"text": "api capture synthetic", "channel": "web", "source_ref": "w1"},
    )
    assert r.status_code == 200
    receipt = r.json()
    assert receipt["status"] == "ledger_only"  # no packs installed → ledger-only
    r = client.get("/api/query", params={"status": "ledger_only"})
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert any(row["id"] == receipt["entry_id"] for row in rows)


def test_non_local_bind_requires_token(tmp_path: Path):
    with pytest.raises(SystemExit):
        run_server(tmp_path / "h", host="0.0.0.0", port=8799, api_token=None)


def test_p4_endpoints_and_drain_loop(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    setup = HarnessAPI(workspace.home)
    setup.init()
    setup.packs.activate_bundled("sourdough")

    # `with` triggers the FastAPI lifespan → background drain loop starts/stops.
    with TestClient(create_app(workspace.home)) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert "projection_lag" in r.json()

        r = client.get("/api/blocks/sourdough/views")
        assert r.status_code == 200
        assert any(v["id"] == "bakes" for v in r.json()["views"])

        r = client.get("/api/blocks/sourdough/bakes/data")
        assert r.status_code == 200
        assert r.json()["block"] == "timeline"

        r = client.get("/api/review/stats")
        assert r.status_code == 200
        assert r.json()["pending"] == 0

        # Drain trigger over HTTP (empty body allowed).
        r = client.post("/api/projections/drain")
        assert r.status_code == 200
        assert "drained_count" in r.json()


def test_drain_projection_filter_reaches_coordinator(workspace, monkeypatch):
    api = HarnessAPI(workspace.home)
    api.init()
    report = Mock()
    report.to_dict.return_value = {"drained_count": 0, "drained": [], "failed": []}
    drain = Mock(return_value=report)
    monkeypatch.setattr(api.projections, "drain_until_empty", drain)

    assert api.drain_projections(adapters=["markdown"], limit=7)["drained_count"] == 0
    drain.assert_called_once_with(adapters=["markdown"], limit=7)


def test_provider_settings_uses_onboarding_status_and_auth(workspace, monkeypatch):
    monkeypatch.delenv("DOMAIN_FOUNDRY_API_TOKEN", raising=False)
    client = TestClient(
        create_app(workspace.home, api_token="settings-secret", enable_drain_loop=False)
    )

    assert client.get("/api/settings/providers").status_code == 401
    response = client.get(
        "/api/settings/providers",
        headers={"Authorization": "Bearer settings-secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) >= {
        "config_file",
        "config_file_exists",
        "provider",
        "mode",
        "detected_env_keys",
        "routine",
        "sota",
    }
    assert all(
        "api_key" not in tier
        for tier in (payload["routine"], payload["sota"])
    )
