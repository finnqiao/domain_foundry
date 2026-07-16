"""P3 gate: approve-exactly-once, correction round-trip, merge orphans, policy matrix."""

from __future__ import annotations

import json

from domain_expert_core.api.harness import HarnessAPI
from domain_expert_core.llm.provider import HeuristicProvider
from domain_expert_core.paths import Workspace
from domain_expert_core.policy.evaluator import evaluate_policy, seed_user_override
from domain_expert_core.routing.router import Router
from domain_expert_core.security.store import connect_rw


def _ready(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    # Activate on the same PackRegistry instance shared by router/executor/pipeline
    api.packs.activate_bundled("sourdough")
    api.packs.activate_bundled("plants")
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    return api


def test_auto_apply_create_writes_canonical_and_revision(workspace: Workspace):
    api = _ready(workspace)
    receipt = api.capture(
        "baked a 75% hydration country loaf, bulk 5h, came out great",
        channel="cli",
        source_ref="bake-1",
    )
    assert receipt.status == "applied"
    assert any(s.domain == "sourdough" for s in receipt.routed)

    conn = connect_rw(workspace.ledger_db)
    try:
        objs = conn.execute(
            "SELECT uid, domain, object_type, status FROM canonical_object"
        ).fetchall()
        assert len(objs) >= 1
        assert objs[0]["domain"] == "sourdough"
        revs = conn.execute("SELECT * FROM object_revision").fetchall()
        assert len(revs) >= 1
        crs = conn.execute(
            "SELECT status, object_uid FROM change_request WHERE entry_id = ?",
            (receipt.entry_id,),
        ).fetchall()
        assert all(r["status"] == "applied" for r in crs)
        assert all(r["object_uid"] for r in crs)
        outbox = conn.execute("SELECT status FROM projection_outbox").fetchall()
        assert outbox and outbox[0]["status"] == "pending"
    finally:
        conn.close()

    dconn = connect_rw(workspace.domains_db)
    try:
        rows = dconn.execute("SELECT * FROM sourdough__bake WHERE tombstoned = 0").fetchall()
        assert len(rows) == 1
        assert rows[0]["hydration"] == 75.0
    finally:
        dconn.close()


def test_approve_applies_exactly_once(workspace: Workspace):
    api = _ready(workspace)
    # Force review via user override on create
    seed_user_override(
        workspace.ledger_db,
        domain="sourdough",
        operation="create",
        action="review",
        min_confidence=0.0,
        priority=1,
    )
    receipt = api.capture(
        "baked a 80% hydration batard",
        channel="cli",
        source_ref="bake-review-1",
    )
    assert receipt.status == "review"
    items = api.review_list(status="pending")
    assert len(items) >= 1
    approval_id = items[0]["approval_id"]
    cr_id = items[0]["change_request_id"]

    first = api.review_resolve(approval_id, decision="approved", resolver="tester")
    assert first["applied"] is True
    assert first["replayed"] is False
    assert first["object_uid"]

    second = api.review_resolve(approval_id, decision="approved", resolver="tester")
    assert second["applied"] is True
    assert second["replayed"] is True
    assert second["object_uid"] == first["object_uid"]

    # Direct double execute also idempotent
    again = api.executor.execute_change_request(cr_id, actor="tester")
    assert again.applied and again.replayed

    conn = connect_rw(workspace.ledger_db)
    try:
        row = conn.execute(
            "SELECT decision_status, application_status FROM approval_queue WHERE id = ?",
            (approval_id,),
        ).fetchone()
        assert row["decision_status"] == "approved"
        assert row["application_status"] == "applied"
        # exactly one applied revision for the object
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM object_revision WHERE object_uid = ?",
            (first["object_uid"],),
        ).fetchone()["n"]
        assert n == 1
    finally:
        conn.close()


def test_crash_between_approve_and_apply_recovers(workspace: Workspace):
    """Simulate crash: decision approved, application not_started → re-resolve applies."""
    api = _ready(workspace)
    seed_user_override(
        workspace.ledger_db,
        domain="sourdough",
        operation="create",
        action="review",
        priority=1,
    )
    api.capture("baked a boule with rye", channel="cli", source_ref="crash-1")
    items = api.review_list()
    assert items
    approval_id = items[0]["approval_id"]
    cr_id = items[0]["change_request_id"]

    # Manually mark decision without applying (crash window)
    conn = connect_rw(workspace.ledger_db)
    try:
        conn.execute(
            """
            UPDATE approval_queue
            SET decision_status = 'approved', application_status = 'not_started'
            WHERE id = ?
            """,
            (approval_id,),
        )
        conn.commit()
    finally:
        conn.close()

    recovered = api.executor.execute_change_request(
        cr_id, actor="recovery", approval_id=approval_id
    )
    assert recovered.applied is True
    assert recovered.replayed is False

    # Second recovery is replay
    recovered2 = api.executor.execute_change_request(
        cr_id, actor="recovery", approval_id=approval_id
    )
    assert recovered2.replayed is True


def test_one_message_correction_round_trip(workspace: Workspace):
    api = _ready(workspace)
    cap = api.capture(
        "baked a 75% hydration country loaf, bulk 5h, came out great",
        channel="cli",
        source_ref="corr-1",
    )
    assert cap.status == "applied"

    corr = api.correct(
        text="that bake was 80% hydration not 75",
        entry_id=cap.entry_id,
        channel="cli",
    )
    assert corr["applied"] is True
    assert corr["action"] == "amend"
    assert corr["correction_event_id"]
    assert corr["eval_case_id"]
    assert corr["object_uid"]

    conn = connect_rw(workspace.ledger_db)
    try:
        revs = conn.execute(
            "SELECT changed_fields_json FROM object_revision WHERE object_uid = ? ORDER BY revision",
            (corr["object_uid"],),
        ).fetchall()
        assert len(revs) >= 2  # create + amend
        amend_diff = json.loads(revs[-1]["changed_fields_json"])
        assert "hydration" in amend_diff
        assert amend_diff["hydration"]["to"] == 80.0

        # provenance chain: interpretation superseded
        interps = conn.execute(
            "SELECT version, status, superseded_by FROM interpretation WHERE entry_id = ? ORDER BY version",
            (cap.entry_id,),
        ).fetchall()
        assert len(interps) >= 2
        assert interps[0]["status"] == "superseded"
        assert interps[-1]["status"] == "applied"

        ce = conn.execute(
            "SELECT wrong_json, right_json FROM correction_event WHERE id = ?",
            (corr["correction_event_id"],),
        ).fetchone()
        assert ce
        wrong = json.loads(ce["wrong_json"])
        right = json.loads(ce["right_json"])
        assert wrong.get("hydration") == 75.0
        assert right.get("hydration") == 80.0

        ec = conn.execute(
            "SELECT source, correction_event_id FROM eval_case WHERE id = ?",
            (corr["eval_case_id"],),
        ).fetchone()
        assert ec["source"] == "correction"
        assert ec["correction_event_id"] == corr["correction_event_id"]
    finally:
        conn.close()

    dconn = connect_rw(workspace.domains_db)
    try:
        row = dconn.execute(
            "SELECT hydration FROM sourdough__bake WHERE object_uid = ?",
            (corr["object_uid"],),
        ).fetchone()
        assert row["hydration"] == 80.0
    finally:
        dconn.close()

    assert (workspace.home / "fewshot.json").exists()


def test_merge_leaves_no_orphans(workspace: Workspace):
    api = _ready(workspace)
    # Create two starters
    api.capture("fed the rye starter", channel="cli", source_ref="st-1")
    api.capture("fed the wheat starter", channel="cli", source_ref="st-2")

    conn = connect_rw(workspace.ledger_db)
    try:
        uids = [
            r["uid"]
            for r in conn.execute(
                """
                SELECT uid FROM canonical_object
                WHERE domain = 'sourdough' AND object_type = 'starter' AND status = 'active'
                ORDER BY created_at
                """
            ).fetchall()
        ]
    finally:
        conn.close()

    # If heuristic routed to bake instead of starter, create starters explicitly
    if len(uids) < 2:
        from domain_expert_core.apply.engine import ApplyEngine, OperationSpec

        engine = ApplyEngine(workspace, registry=api.packs)
        a = engine.apply_spec(
            OperationSpec(
                domain="sourdough",
                operation="create",
                object_type="starter",
                payload={"name": "rye"},
            )
        )
        b = engine.apply_spec(
            OperationSpec(
                domain="sourdough",
                operation="create",
                object_type="starter",
                payload={"name": "wheat"},
            )
        )
        assert a.ok and b.ok
        uids = [a.object_uid, b.object_uid]  # type: ignore[list-item]

    merged = api.correct(
        action="merge",
        object_uid=uids[0],
        merge_into_uid=uids[1],
        text="merge those two starters",
    )
    assert merged["applied"] is True
    assert merged["object_uid"] == uids[1]

    conn = connect_rw(workspace.ledger_db)
    try:
        orphans = conn.execute(
            """
            SELECT uid FROM canonical_object
            WHERE status = 'merged' AND merged_into_uid IS NULL
            """
        ).fetchall()
        assert orphans == []
        src = conn.execute(
            "SELECT status, merged_into_uid FROM canonical_object WHERE uid = ?",
            (uids[0],),
        ).fetchone()
        assert src["status"] == "merged"
        assert src["merged_into_uid"] == uids[1]
        # FK check clean
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert fk == []
    finally:
        conn.close()


def test_policy_matrix_auto_review_confirm(workspace: Workspace):
    api = _ready(workspace)

    # auto_apply at high confidence
    d = evaluate_policy(
        workspace.ledger_db,
        domain="sourdough",
        operation="create",
        object_type="bake",
        channel="cli",
        confidence=0.9,
        pack=api.packs.get("sourdough"),
    )
    assert d.action == "auto_apply"

    # below min_confidence → review
    d2 = evaluate_policy(
        workspace.ledger_db,
        domain="sourdough",
        operation="create",
        object_type="bake",
        channel="cli",
        confidence=0.5,
        pack=api.packs.get("sourdough"),
    )
    assert d2.action == "review"

    # delete → review by pack default
    d3 = evaluate_policy(
        workspace.ledger_db,
        domain="sourdough",
        operation="delete",
        object_type="bake",
        channel="cli",
        confidence=0.99,
        pack=api.packs.get("sourdough"),
    )
    assert d3.action == "review"

    # user override wins
    seed_user_override(
        workspace.ledger_db,
        domain="sourdough",
        operation="create",
        channel="email",
        action="confirm",
        priority=1,
    )
    d4 = evaluate_policy(
        workspace.ledger_db,
        domain="sourdough",
        operation="create",
        object_type="bake",
        channel="email",
        confidence=0.95,
        pack=api.packs.get("sourdough"),
    )
    assert d4.action == "confirm"
    assert d4.source == "user"
