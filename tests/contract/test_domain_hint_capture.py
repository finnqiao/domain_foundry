"""Domain-scoped capture is available in-process and over HTTP."""

from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.routing.router import Router


def _ready(workspace) -> tuple[HarnessAPI, TestClient]:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.packs.activate_bundled("plants")
    api.packs.reload()
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    client = TestClient(create_app(workspace.home, enable_drain_loop=False))
    return api, client


def test_domain_hint_is_echoed_and_scopes_capture(workspace):
    api, client = _ready(workspace)

    cross_domain = api.capture("watered the monstera", channel="web")
    assert cross_domain.status == "applied"
    assert all(span.domain != "sourdough" for span in cross_domain.routed)

    hinted = api.capture("fed the rye starter", channel="web", domain_hint="sourdough")
    assert hinted.status == "applied"
    assert hinted.domain_hint == "sourdough"
    assert any(span.domain == "sourdough" for span in hinted.routed)

    response = client.post(
        "/api/capture",
        json={
            "text": "fed the wheat starter",
            "channel": "web",
            "domain_hint": "sourdough",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["domain_hint"] == "sourdough"
    assert any(span["domain"] == "sourdough" for span in payload["routed"])
