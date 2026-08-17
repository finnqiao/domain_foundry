"""Held-out coffee/climbing proof through the generic pack contract."""

from __future__ import annotations

from pathlib import Path

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.paths import Workspace
from domain_foundry_core.projections.blockdata import BlockDataService
from domain_foundry_core.routing.router import Router

REPO = Path(__file__).resolve().parents[2]
HELDOUT = REPO / "examples" / "heldout" / "packs"


def test_heldout_coffee_and_climbing_load_without_core_domain_branches(workspace: Workspace):
    api = HarnessAPI(workspace.home)
    api.init()
    api.pack_add(HELDOUT / "coffee")
    api.pack_add(HELDOUT / "climbing")
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())

    coffee = api.capture(
        "V60 Ethiopian brew with 15g coffee and 250g water, blueberry notes",
        channel="test",
        source_ref="heldout-coffee-1",
    )
    climbing = api.capture(
        "sent a tough V5 on the overhang today, crux was the heel hook",
        channel="test",
        source_ref="heldout-climbing-1",
    )
    assert any(span.domain == "coffee" for span in coffee.routed), coffee
    assert any(span.domain == "climbing" for span in climbing.routed), climbing

    service = BlockDataService(workspace, registry=api.packs)
    assert {view["block"] for view in service.views("coffee")} == {
        "timeline",
        "compare",
        "gallery",
    }
    compare = service.view_data("coffee", "compare")
    assert compare["block"] == "compare"
    assert compare["metrics"][0]["id"] == "brew_ratio"
    assert service.view_data("climbing", "sessions")["block"] == "timeline"
    assert service.view_data("climbing", "routes")["block"] == "list"

    capabilities = REPO / "core" / "domain_foundry_core"
    for path in capabilities.rglob("*.py"):
        if path.name in {"capabilities.py", "blockdata.py"}:
            source = path.read_text(encoding="utf-8").lower()
            assert "coffee" not in source
            assert "climbing" not in source
