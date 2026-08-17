"""API security contract: bearer-token gating and localhost-open default.

Complements `tests/contract/test_api.py::test_non_local_bind_requires_token`
(which covers the refuse-to-start guard) by asserting the request-level token
middleware actually gates endpoints once a token is configured, and that the
default localhost posture stays open — for reads and writes — for zero-friction
local use (non-local binds refuse to start without a token; see `run_server`).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI


def _client(home: Path, token: str | None) -> TestClient:
    HarnessAPI(home).init()
    return TestClient(create_app(home, api_token=token, enable_drain_loop=False))


def test_token_gates_endpoints(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DOMAIN_FOUNDRY_API_TOKEN", raising=False)
    home = tmp_path / "home"
    client = _client(home, token="s3cret-synthetic")

    # No credential → 401.
    assert client.get("/health").status_code == 401

    # Wrong credential → 403.
    bad = client.get("/health", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 403

    # Malformed scheme → 401.
    malformed = client.get("/health", headers={"Authorization": "s3cret-synthetic"})
    assert malformed.status_code == 401

    # Correct credential → 200, and mutations are gated the same way.
    ok = client.get("/health", headers={"Authorization": "Bearer s3cret-synthetic"})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    # Writes are back (ADR-006) and are gated exactly like reads: 401 without
    # a credential, 200 with the correct one.
    denied = client.post("/api/capture", json={"text": "synthetic", "channel": "web"})
    assert denied.status_code == 401
    with_token = client.post(
        "/api/capture",
        json={"text": "synthetic", "channel": "web"},
        headers={"Authorization": "Bearer s3cret-synthetic"},
    )
    assert with_token.status_code == 200
    assert with_token.json()["entry_id"]


def test_localhost_default_is_open(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DOMAIN_FOUNDRY_API_TOKEN", raising=False)
    home = tmp_path / "home"
    client = _client(home, token=None)

    # No token configured (local-only default): endpoints are reachable.
    assert client.get("/health").status_code == 200
    # No token configured (local-only default): writes are open too.
    r = client.post("/api/capture", json={"text": "open local capture", "channel": "web"})
    assert r.status_code == 200


def test_token_is_bootstrapped_into_served_spa(tmp_path: Path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><head></head><body>app</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr("domain_foundry_core.api.app._app_dist", lambda: dist)

    client = _client(tmp_path / "home", token="s3cret-</script>")
    response = client.get("/")
    assert response.status_code == 200
    assert 'window.__DE_TOKEN__ = "s3cret-\\u003c/script>";' in response.text
    sources = client.get("/sources")
    assert sources.status_code == 200
    assert 'window.__DE_TOKEN__ = "s3cret-\\u003c/script>";' in sources.text
