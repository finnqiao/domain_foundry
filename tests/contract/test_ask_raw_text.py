"""Ask prefers original capture prose over FTS snippet dumps."""

from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.routing.router import Router


def test_ask_cites_original_sentence(workspace):
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.packs.reload()
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    sentence = "baked a 75% hydration country loaf after a long bulk"
    api.capture(sentence, channel="web")

    client = TestClient(create_app(workspace.home, enable_drain_loop=False))
    response = client.post(
        "/api/ask",
        json={"question": "what did I bake?", "domain": "sourdough"},
    )
    assert response.status_code == 200
    payload = response.json()
    blob = json_blob(payload)
    assert "country loaf" in blob
    assert "75%" in blob or "hydration" in blob


def json_blob(payload: dict) -> str:
    import json

    return json.dumps(payload).lower()
