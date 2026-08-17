"""HTTP Ask/search contract and daily cost-cap behavior."""

from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.routing.cost import CostGuard
from domain_foundry_core.routing.router import Router


def _ready(workspace) -> tuple[HarnessAPI, TestClient]:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.packs.reload()
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    api.capture("baked a 75% hydration country loaf", channel="web")
    return api, TestClient(create_app(workspace.home, enable_drain_loop=False))


def test_ask_and_search_are_grounded_and_cost_free_without_a_model(workspace):
    api, client = _ready(workspace)
    response = client.post(
        "/api/ask",
        json={"question": "what hydration was my loaf?", "domain": "sourdough"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "search_only"
    assert payload["cost_usd"] == 0
    assert payload["citations"]
    assert payload["daily_cap_usd"] > 0

    search = client.get("/api/search", params={"q": "loaf"})
    assert search.status_code == 200
    assert search.json()["total"] >= 1

    before = api.query(domain="sourdough")
    client.post("/api/ask", json={"question": "show my loaf", "domain": "sourdough"})
    assert len(api.query(domain="sourdough")) == len(before)


def test_ask_uses_search_only_after_daily_cap(workspace):
    _api, client = _ready(workspace)
    guard = CostGuard(_api.workspace.ledger_db)
    guard.record(
        provider="test",
        model="test-model",
        input_tokens=0,
        output_tokens=0,
        cost_usd=1.0,
        tier="routine",
    )
    response = client.post(
        "/api/ask",
        json={"question": "what hydration was my loaf?", "domain": "sourdough"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["cap_hit"] is True
    assert payload["mode"] == "search_only"
    assert payload["daily_cap_usd"] == guard.config.daily_usd_cap
