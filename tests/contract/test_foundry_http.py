from __future__ import annotations

from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app


def test_foundry_goldens_are_available_over_the_authenticated_http_contract(tmp_path) -> None:
    client = TestClient(
        create_app(tmp_path, api_token="secret", enable_drain_loop=False)
    )
    assert client.get("/api/foundry/goldens").status_code == 401

    response = client.get(
        "/api/foundry/goldens", headers={"Authorization": "Bearer secret"}
    )
    assert response.status_code == 200
    goldens = response.json()["goldens"]
    assert {item["id"] for item in goldens} == {
        "card-collector",
        "japanese-study-coach",
        "sourdough-lab",
    }
    assert len({item["topology"] for item in goldens}) == 3

    detail = client.get(
        "/api/foundry/goldens/card-collector",
        headers={"Authorization": "Bearer secret"},
    )
    assert detail.status_code == 200
    assert "localStorage" in detail.json()["owned_app_html"]


def test_foundry_proposal_does_not_fall_back_to_keyword_scaffolding(
    tmp_path, monkeypatch
) -> None:
    class OfflineProvider:
        def has_live_keys(self) -> bool:
            return False

    monkeypatch.setattr(
        "domain_foundry_core.foundry.service.build_tiered_provider",
        lambda _home: OfflineProvider(),
    )
    client = TestClient(create_app(tmp_path, enable_drain_loop=False))
    response = client.post(
        "/api/foundry/proposals",
        json={
            "goal": "Understand my vintage trail-map collection",
            "artifacts": ["photo folder"],
            "constraints": ["offline"],
            "acceptance_tasks": [
                {"input": "Add one map", "expected": "See its edition lineage"},
                {"input": "Compare editions", "expected": "See their differences"},
            ],
            "web_research": False,
        },
    )
    assert response.status_code == 409
    assert "keyword scaffold is intentionally not used" in response.json()["detail"]


def test_foundry_app_path_rejects_path_traversal(tmp_path) -> None:
    client = TestClient(create_app(tmp_path, enable_drain_loop=False))
    response = client.get("/api/foundry/apps/not-a-valid-ulid")
    assert response.status_code == 400


def test_foundry_brief_has_bounded_request_fields(tmp_path) -> None:
    client = TestClient(create_app(tmp_path, enable_drain_loop=False))
    response = client.post(
        "/api/foundry/proposals",
        json={
            "goal": "x" * 4_001,
            "acceptance_tasks": [
                {"input": "Do one thing", "expected": "Observe one result"},
                {"input": "Do another thing", "expected": "Observe another result"},
            ],
        },
    )
    assert response.status_code == 422
