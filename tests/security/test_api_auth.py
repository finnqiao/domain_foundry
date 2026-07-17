"""API security contract: bearer-token gating and localhost-open default.

Complements `tests/contract/test_api.py::test_non_local_bind_requires_token`
(which covers the refuse-to-start guard) by asserting the request-level token
middleware actually gates endpoints once a token is configured, and that the
default localhost posture stays open for zero-friction local use.
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

    denied = client.post("/api/capture", json={"text": "synthetic", "channel": "web"})
    assert denied.status_code == 401
    allowed = client.post(
        "/api/capture",
        json={"text": "synthetic", "channel": "web"},
        headers={"Authorization": "Bearer s3cret-synthetic"},
    )
    assert allowed.status_code == 200


def test_localhost_default_is_open(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DOMAIN_FOUNDRY_API_TOKEN", raising=False)
    home = tmp_path / "home"
    client = _client(home, token=None)

    # No token configured (local-only default): endpoints are reachable.
    assert client.get("/health").status_code == 200
