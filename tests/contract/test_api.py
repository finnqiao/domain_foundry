from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app, run_server
from domain_foundry_core.api.harness import HarnessAPI


def test_fastapi_reads_serve_writes_are_gone(workspace, monkeypatch):
    """Mesh P0: writes happen in-process; the HTTP surface is read-only."""
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    client = TestClient(create_app(workspace.home))

    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Write endpoint is gone — 410 with a pointer to the in-process path.
    r = client.post(
        "/api/capture",
        json={"text": "api capture synthetic", "channel": "web", "source_ref": "w1"},
    )
    assert r.status_code == 410
    assert "in-process" in r.json()["detail"]

    # The same write via the embedded harness is visible through HTTP reads.
    receipt = api.capture("api capture synthetic", channel="web", source_ref="w1")
    assert receipt.status == "ledger_only"
    r = client.get("/api/query", params={"status": "ledger_only"})
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert any(row["id"] == receipt.entry_id for row in rows)


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

        # Drain trigger moved in-process with the rest of the write surface.
        r = client.post("/api/projections/drain")
        assert r.status_code == 410
        assert "drained_count" in setup.drain_projections()
