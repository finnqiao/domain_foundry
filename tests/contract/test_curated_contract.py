"""P7 curated contract-case set (plan §10.1 curated cases, §10.3 gate).

Five hand-written invariant cases that run alongside the corpus replay in CI:
  1. approval executes exactly once
  2. never-drop ladder (unroutable capture is never silently dropped)
  3. multi-domain fan-out (one message -> multiple domains + cross-links)
  4. idempotent re-capture (same source_ref -> one entry)
  5. projection convergence (auto-apply -> outbox -> drained/refreshed)

These are the substrate-invariant gate the plan requires to run with the eval
corpus. They overlap intentionally with the P3/P4 gate tests but are collected
here as the named curated set so the P7 gate narrative is self-contained.
"""

from __future__ import annotations

from domain_expert_core.api.harness import HarnessAPI
from domain_expert_core.llm.provider import HeuristicProvider
from domain_expert_core.paths import Workspace
from domain_expert_core.policy.evaluator import seed_user_override
from domain_expert_core.routing.router import Router
from domain_expert_core.security.store import connect_ro


def _ready(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.packs.activate_bundled("plants")
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    return api


def test_curated_approval_executes_exactly_once(workspace: Workspace):
    api = _ready(workspace)
    seed_user_override(
        workspace.ledger_db,
        domain="sourdough",
        operation="create",
        action="review",
        min_confidence=0.0,
        priority=1,
    )
    receipt = api.capture("baked an 80% hydration batard", channel="cli", source_ref="c-1")
    assert receipt.status == "review"
    item = api.review_list(status="pending")[0]

    first = api.review_resolve(item["approval_id"], decision="approved")
    second = api.review_resolve(item["approval_id"], decision="approved")
    assert first["applied"] and not first["replayed"]
    assert second["replayed"] and second["object_uid"] == first["object_uid"]

    conn = connect_ro(workspace.ledger_db)
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM object_revision WHERE object_uid = ?",
            (first["object_uid"],),
        ).fetchone()["n"]
    finally:
        conn.close()
    assert n == 1


def test_curated_never_drop_ladder(workspace: Workspace):
    api = _ready(workspace)
    receipt = api.capture("the quarterly board meeting ran long", channel="cli", source_ref="c-2")
    assert receipt.status == "unfiled"

    conn = connect_ro(workspace.ledger_db)
    try:
        entry = conn.execute(
            "SELECT status FROM entry WHERE id = ?", (receipt.entry_id,)
        ).fetchone()
        card = conn.execute(
            "SELECT status FROM unfiled_card WHERE entry_id = ?", (receipt.entry_id,)
        ).fetchone()
    finally:
        conn.close()
    # Nothing dropped: durable entry + an open unfiled card to triage later.
    assert entry is not None
    assert card is not None and card["status"] == "open"


def test_curated_multi_domain_fan_out(workspace: Workspace):
    api = _ready(workspace)
    receipt = api.capture(
        "watered the monstera and baked a 75% hydration loaf",
        channel="cli",
        source_ref="c-3",
    )
    domains = {s.domain for s in receipt.routed if s.domain}
    assert {"plants", "sourdough"} <= domains

    conn = connect_ro(workspace.ledger_db)
    try:
        crs = conn.execute(
            "SELECT domain FROM change_request WHERE entry_id = ?", (receipt.entry_id,)
        ).fetchall()
        links = conn.execute(
            "SELECT COUNT(*) AS n FROM object_link WHERE entry_id = ?",
            (receipt.entry_id,),
        ).fetchone()["n"]
    finally:
        conn.close()
    assert len({r["domain"] for r in crs}) >= 2
    assert links >= 1


def test_curated_idempotent_recapture(workspace: Workspace):
    api = _ready(workspace)
    r1 = api.capture("fed the rye starter", channel="telegram", source_ref="dup-9")
    r2 = api.capture("fed the rye starter (echo)", channel="telegram", source_ref="dup-9")
    assert r2.idempotent_replay is True
    assert r2.entry_id == r1.entry_id

    conn = connect_ro(workspace.ledger_db)
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM entry WHERE id = ?", (r1.entry_id,)
        ).fetchone()["n"]
        total = conn.execute("SELECT COUNT(*) AS n FROM capture_event").fetchone()["n"]
    finally:
        conn.close()
    assert n == 1 and total == 1


def test_curated_projection_convergence(workspace: Workspace):
    api = _ready(workspace)
    receipt = api.capture(
        "baked a 75% hydration country loaf, bulk 5h, came out great",
        channel="cli",
        source_ref="c-5",
    )
    assert receipt.status == "applied"
    assert api.projection_status(entry_id=receipt.entry_id)["projection_status"] == "pending"

    restarted = HarnessAPI(workspace.home)
    report = restarted.drain_projections()
    assert report["failed_count"] == 0
    assert report["drained_count"] >= 2
    after = restarted.projection_status(entry_id=receipt.entry_id)
    assert after["projection_status"] == "refreshed"
