"""Canonical data export is portable and does not leak secrets."""

import json

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.cli import app
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.routing.router import Router


def _ready(workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.packs.reload()
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    return api


def test_export_shape_redacts_values_and_http_unknown_domain(workspace):
    api = _ready(workspace)
    receipt = api.capture(
        "baked a country loaf with sk-ant-fakekey123",
        channel="web",
    )
    payload = api.export_data(domain="sourdough")
    dumped = json.dumps(payload)
    assert payload["format"] == "domain-foundry-export/1"
    assert payload["counts"]["sourdough"]["bake"] >= 1
    assert "sk-ant-fakekey123" not in dumped
    assert any(
        item["entry_id"] == receipt.entry_id
        for item in payload["domains"]["sourdough"]["objects"]["bake"]
    )

    client = TestClient(create_app(workspace.home, enable_drain_loop=False))
    response = client.get("/api/export", params={"domain": "nope"})
    assert response.status_code == 404
    response = client.get("/api/export", params={"domain": "sourdough"})
    assert response.status_code == 200
    assert response.json()["format"] == "domain-foundry-export/1"


def test_top_level_export_is_json_and_truthful_for_empty_home(tmp_path):
    home = tmp_path / "empty-home"
    result = CliRunner().invoke(app, ["--home", str(home), "export", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["format"] == "domain-foundry-export/1"
    assert payload["domains"] == {}
    assert payload["counts"] == {}

    destination = tmp_path / "nested" / "export.json"
    result = CliRunner().invoke(
        app,
        ["--home", str(home), "export", "--out", str(destination)],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(destination.read_text(encoding="utf-8"))["format"] == (
        "domain-foundry-export/1"
    )
