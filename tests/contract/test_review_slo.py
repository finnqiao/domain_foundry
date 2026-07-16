"""P4 gate: review queue SLO counters, diff previews, and bulk ops."""

from __future__ import annotations

from domain_expert_core.api.harness import HarnessAPI
from domain_expert_core.llm.provider import HeuristicProvider
from domain_expert_core.paths import Workspace
from domain_expert_core.policy.evaluator import seed_user_override
from domain_expert_core.routing.router import Router
from domain_expert_core.security.store import connect_rw


def _ready(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.packs.activate_bundled("plants")
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    # Force every create into review so we build a backlog deterministically.
    seed_user_override(
        workspace.ledger_db,
        domain="sourdough",
        operation="create",
        action="review",
        min_confidence=0.0,
        priority=1,
    )
    return api


def _age_approvals(workspace: Workspace, approval_ids: list[str], created_at: str) -> None:
    conn = connect_rw(workspace.ledger_db)
    try:
        for aid in approval_ids:
            conn.execute(
                "UPDATE approval_queue SET created_at = ? WHERE id = ?",
                (created_at, aid),
            )
        conn.commit()
    finally:
        conn.close()


def test_review_slo_counters_accurate(workspace: Workspace):
    api = _ready(workspace)
    for i in range(4):
        api.capture(
            f"baked a {70 + i}% hydration loaf",
            channel="cli",
            source_ref=f"slo-{i}",
        )
    items = api.review_list()
    assert len(items) == 4
    ids = [it["approval_id"] for it in items]

    # Age two of them well past the 24h SLO (frozen clock = 2026-07-16T12:00:00Z).
    _age_approvals(workspace, ids[:2], "2026-07-14T12:00:00Z")

    stats = api.review_stats()
    assert stats["pending"] == 4
    assert stats["overdue"] == 2
    # Oldest is 2 days old.
    assert stats["oldest_pending_age_seconds"] == 2 * 24 * 3600
    assert stats["by_domain"].get("sourdough") == 4

    overdue_items = api.review_list(overdue_only=True, include_diff=True)
    assert len(overdue_items) == 2
    assert all(it["overdue"] for it in overdue_items)


def test_review_diff_proposed_vs_current(workspace: Workspace):
    api = _ready(workspace)
    cap = api.capture(
        "baked a 75% hydration country loaf, came out great",
        channel="cli",
        source_ref="diff-1",
    )
    items = api.review_list(status="pending", include_diff=True)
    assert items
    item = next(it for it in items if it["change_request_id"])
    diff = item["diff"]
    assert diff["is_new"] is True
    # Proposed hydration should be present in the diff preview.
    hydration = next((f for f in diff["fields"] if f["field"] == "hydration"), None)
    assert hydration is not None
    assert hydration["proposed"] == 75

    # Standalone diff endpoint returns the same shape.
    standalone = api.review_diff(item["approval_id"])
    assert standalone["operation"] == "create"
    assert cap.status == "review"


def test_review_bulk_resolve_applies_all(workspace: Workspace):
    api = _ready(workspace)
    for i in range(3):
        api.capture(f"baked loaf number {i}", channel="cli", source_ref=f"bulk-{i}")
    items = api.review_list()
    ids = [it["approval_id"] for it in items]
    assert len(ids) == 3

    result = api.review_resolve_bulk(ids, decision="approved", resolver="tester")
    assert result["count"] == 3
    assert result["applied"] == 3
    assert result["failed"] == 0

    # Queue drains to zero pending.
    assert api.review_list() == []
    stats = api.review_stats()
    assert stats["pending"] == 0
    assert stats["overdue"] == 0
