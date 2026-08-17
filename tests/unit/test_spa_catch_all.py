"""History-API deep links serve the SPA without swallowing API 404s."""

from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app


def test_deep_link_serves_index_html(workspace):
    client = TestClient(create_app(workspace.home, enable_drain_loop=False))
    root = client.get("/")
    if root.headers.get("content-type", "").startswith("text/html"):
        response = client.get("/passions/sourdough/bakes")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")


def test_unknown_api_path_is_json_404(workspace):
    client = TestClient(create_app(workspace.home, enable_drain_loop=False))
    response = client.get("/api/definitely-not-a-thing")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
