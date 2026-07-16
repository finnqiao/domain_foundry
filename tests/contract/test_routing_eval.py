from __future__ import annotations

from pathlib import Path

from domain_expert_core.api.harness import HarnessAPI
from domain_expert_core.evals.runner import run_eval
from domain_expert_core.llm.provider import HeuristicProvider
from domain_expert_core.packs.registry import PackRegistry
from domain_expert_core.paths import Workspace
from domain_expert_core.routing.cost import CostGuard, CostGuardConfig
from domain_expert_core.routing.router import Router
from domain_expert_core.security.store import connect_rw

CASES = Path(__file__).resolve().parents[2] / "examples" / "synthetic" / "routing_eval.jsonl"


def test_routing_eval_gate(workspace: Workspace):
    report = run_eval(CASES, workspace=workspace, packs=["plants", "sourdough"])
    assert report.total >= 60, report.total
    assert report.accuracy >= 0.90, (
        f"accuracy {report.accuracy:.3f} < 0.90; "
        f"failures={[s for s in report.scores if not s.ok][:8]}"
    )


def test_multi_domain_fanout_creates_links(workspace: Workspace):
    registry = PackRegistry(workspace)
    registry.activate_bundled("plants")
    registry.activate_bundled("sourdough")
    router = Router(workspace, registry=registry, llm=HeuristicProvider())
    api = HarnessAPI(workspace.home)
    # ensure same workspace packs
    api.packs = registry
    api.router = router
    receipt = api.capture(
        "watered the monstera and baked a 75% hydration loaf",
        channel="cli",
        source_ref="multi-1",
    )
    domains = {s.domain for s in receipt.routed if s.domain}
    assert "plants" in domains and "sourdough" in domains

    conn = connect_rw(workspace.ledger_db)
    try:
        crs = conn.execute(
            "SELECT id, domain FROM change_request WHERE entry_id = ?",
            (receipt.entry_id,),
        ).fetchall()
        assert len(crs) >= 2
        links = conn.execute(
            "SELECT * FROM object_link WHERE entry_id = ?",
            (receipt.entry_id,),
        ).fetchall()
        assert len(links) >= 1
    finally:
        conn.close()


def test_cost_guard_trips(workspace: Workspace):
    registry = PackRegistry(workspace)
    registry.activate_bundled("plants")
    guard = CostGuard(workspace.ledger_db, CostGuardConfig(daily_usd_cap=0.0001))
    guard.record(
        provider="test",
        model="x",
        input_tokens=10,
        output_tokens=10,
        cost_usd=1.0,
    )
    assert guard.allow_llm() is False

    router = Router(workspace, registry=registry, llm=HeuristicProvider(), cost_cap=0.0001)
    # force spend
    router.cost.record(
        provider="test", model="x", input_tokens=1, output_tokens=1, cost_usd=1.0
    )
    result = router.route_text("watered the monstera")
    assert result.spans
    assert result.interpreter in {"heuristic", "rules", "rules_only_cost_guard", "heuristic_fallback"}


def test_pack_validate_and_list(workspace: Workspace):
    api = HarnessAPI(workspace.home)
    api.pack_add(Path(__file__).resolve().parents[2] / "packs" / "plants", force=True)
    listed = api.pack_list()
    assert any(p["name"] == "plants" for p in listed)
    assert api.pack_validate("plants") == []
