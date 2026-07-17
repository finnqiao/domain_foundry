"""P4 unit tests: block-data compilation, coordinator drain/lag, health lag."""

from __future__ import annotations

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.paths import Workspace
from domain_foundry_core.projections.blockdata import BlockDataError, BlockDataService
from domain_foundry_core.routing.router import Router


def _ready(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    return api


def test_block_data_timeline_list_stats(workspace: Workspace):
    api = _ready(workspace)
    api.capture(
        "baked a 75% hydration country loaf, came out great",
        channel="cli",
        source_ref="bd-1",
    )
    api.capture(
        "baked an 80% hydration batard, came out good",
        channel="cli",
        source_ref="bd-2",
    )
    api.drain_projections()

    svc = BlockDataService(workspace, registry=api.packs)

    timeline = svc.view_data("sourdough", "bakes")
    assert timeline["block"] == "timeline"
    assert timeline["date_field"] == "baked_at"
    assert timeline["count"] == 2

    stats = svc.view_data("sourdough", "stats")
    assert stats["block"] == "stats"
    measures = {m["field"]: m for m in stats["measures"]}
    assert "result" in measures
    assert measures["result"]["agg"] == "distribution"
    assert sum(measures["result"]["distribution"].values()) == 2

    starters = svc.view_data("sourdough", "starters")
    assert starters["block"] == "list"
    assert "group_by" in starters


def test_block_data_rejects_unknown_view(workspace: Workspace):
    api = _ready(workspace)
    svc = BlockDataService(workspace, registry=api.packs)
    try:
        svc.view_data("sourdough", "does_not_exist")
    except BlockDataError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected BlockDataError")


def test_health_reports_projection_lag(workspace: Workspace):
    api = _ready(workspace)
    api.capture("baked a rye boule", channel="cli", source_ref="lag-1")

    health = api.health()
    assert health.projection_lag.pending >= 1
    assert health.projection_lag.oldest_pending_age_seconds is not None

    api.drain_projections()
    health2 = api.health()
    assert health2.projection_lag.pending == 0
    assert health2.projection_lag.by_adapter  # watermarks recorded


def test_mark_dirty_coalesces_pending(workspace: Workspace):
    from domain_foundry_core.projections.coordinator import ProjectionCoordinator
    from domain_foundry_core.security.store import connect_ro

    api = _ready(workspace)
    coord = ProjectionCoordinator(workspace, registry=api.packs)
    id1 = coord.mark_dirty(adapter="app_feed", object_key="sourdough:bake")
    id2 = coord.mark_dirty(adapter="app_feed", object_key="sourdough:bake")
    assert id1 == id2  # coalesced onto the same pending row

    conn = connect_ro(workspace.ledger_db)
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM projection_outbox "
            "WHERE adapter = 'app_feed' AND object_key = 'sourdough:bake' "
            "AND status = 'pending'"
        ).fetchone()["n"]
        assert n == 1
    finally:
        conn.close()
