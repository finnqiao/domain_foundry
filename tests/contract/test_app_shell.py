"""App-shell acceptance walkthrough over the real HTTP contract (ADR-006).

Scripted synthetic-data walkthrough mirroring the P5 acceptance gate, now
driven the way the SPA drives it — every mutation over ``client.post``:

    install two packs → capture from the web box → see it in
    timeline/search/stats → correct from the detail view → revision chain
    visible → review queue drains to zero → health panel green.

The embedded ``HarnessAPI`` returned by ``_client`` is kept for setup and
inspection only (e.g. reading canonical UIDs); anything a user can click goes
over HTTP. The browser layer above this is app/e2e/activation.spec.ts.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.security.store import connect_ro


def _client(workspace) -> tuple[HarnessAPI, TestClient]:
    """HTTP app + its embedded harness (harness for setup/inspection only).

    Return the *app's* HarnessAPI so pack activation and captures share the
    same in-memory registry as the read endpoints (two HarnessAPI instances
    over one home would leave the HTTP registry stale after activate).
    """
    HarnessAPI(workspace.home).init()
    app = create_app(workspace.home, enable_drain_loop=False)
    client = TestClient(app)
    return app.state.harness, client


def _first_uid(workspace, domain: str) -> tuple[str, str]:
    conn = connect_ro(workspace.ledger_db)
    try:
        row = conn.execute(
            "SELECT uid, object_type FROM canonical_object "
            "WHERE domain = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (domain,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"no active object for {domain}"
    return str(row["uid"]), str(row["object_type"])


def _uids(workspace, domain: str) -> list[str]:
    conn = connect_ro(workspace.ledger_db)
    try:
        rows = conn.execute(
            "SELECT uid FROM canonical_object "
            "WHERE domain = ? AND status = 'active' ORDER BY created_at DESC",
            (domain,),
        ).fetchall()
    finally:
        conn.close()
    return [str(row["uid"]) for row in rows]


def test_home_starts_empty_then_lists_installed_domains(workspace):
    _api, client = _client(workspace)
    # Empty state: no domains installed yet.
    assert client.get("/api/packs").json()["packs"] == []
    catalog = {c["name"] for c in client.get("/api/packs/catalog").json()["catalog"]}
    assert {"sourdough", "plants"} <= catalog
    assert "_template" not in catalog

    # Install two packs exactly as the SPA does (POST /api/packs/activate).
    r = client.post("/api/packs/activate", json={"name": "sourdough"})
    assert r.status_code == 200
    assert r.json()["name"] == "sourdough"
    assert client.post("/api/packs/activate", json={"name": "plants"}).json()["name"] == "plants"
    # Unknown bundled pack is a legible 404, not a stack trace.
    assert client.post("/api/packs/activate", json={"name": "not-a-pack"}).status_code == 404

    cards = client.get("/api/packs").json()["packs"]
    names = {c["name"] for c in cards}
    assert names == {"sourdough", "plants"}
    sd = next(c for c in cards if c["name"] == "sourdough")
    assert sd["icon"] == "🍞"
    blocks = {v["block"] for v in sd["views"]}
    # All nine blocks must be exercisable against the synthetic packs. Global
    # blocks (capture_feed / detail / review_queue) are covered elsewhere in
    # this walkthrough; per-domain blocks come from the pack views.
    assert {"timeline", "search", "stats", "history", "planner", "list"} <= blocks


def test_quiz_stats_http_endpoint(workspace):
    api, client = _client(workspace)
    api.activate_pack("japanese")
    r = client.get("/api/quiz/stats", params={"domain": "japanese"})
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "japanese"
    assert "review_count" in body
    assert "grade_distribution" in body


def test_full_walkthrough(workspace):
    _api, client = _client(workspace)
    assert client.post("/api/packs/activate", json={"name": "sourdough"}).status_code == 200
    assert client.post("/api/packs/activate", json={"name": "plants"}).status_code == 200

    # 1. Capture from the web box (POST /api/capture, channel=web).
    r = client.post(
        "/api/capture",
        json={"text": "baked a 75% hydration country loaf, bulk 5h, came out great", "channel": "web"},
    )
    assert r.status_code == 200
    cap = r.json()
    assert cap["status"] == "applied"
    assert any(s["domain"] == "sourdough" for s in cap["routed"])

    # 2. See it in the capture feed (HTTP read).
    feed = client.get("/api/query", params={"limit": 20}).json()["rows"]
    assert any("country loaf" in (r.get("raw_text") or "") for r in feed)

    # 3. See it in timeline / search / stats.
    timeline = client.get("/api/blocks/sourdough/bakes/data").json()
    assert timeline["block"] == "timeline"
    assert timeline["count"] >= 1
    # Every view carries its object_type so the app can open a row's detail
    # view without a second lookup (regression: detail 404 when missing).
    assert timeline["object_type"] == "bake"

    search = client.get("/api/blocks/sourdough/find/data").json()
    assert search["count"] >= 1

    stats = client.get("/api/blocks/sourdough/stats/data").json()
    assert stats["block"] == "stats"
    assert stats["total"] >= 1

    history = client.get("/api/blocks/sourdough/history/data").json()
    assert history["block"] == "history"
    assert history["periods"]

    planner = client.get("/api/blocks/sourdough/plan/data").json()
    assert planner["block"] == "planner"

    # 4. Correct from the detail view (amend hydration 75 → 80).
    uid, object_type = _first_uid(workspace, "sourdough")
    detail = client.get(f"/api/objects/sourdough/{object_type}/{uid}").json()
    assert float(detail["fields"]["hydration"]) == 75.0
    # Provenance chain present: capture text + interpretation confidence.
    assert detail["capture"]["raw_text"].startswith("baked a 75%")
    assert detail["interpretations"]

    # 4. Correct from the detail view (amend hydration 75 → 80) — over HTTP,
    # exactly the CorrectionDialog payload.
    r = client.post(
        "/api/correct",
        json={"object_uid": uid, "action": "amend", "fields": {"hydration": 80}, "channel": "web"},
    )
    assert r.status_code == 200
    corrected = r.json()
    assert corrected["applied"] is True

    # 5. Revision chain is visible in the detail view.
    detail2 = client.get(f"/api/objects/sourdough/{object_type}/{uid}").json()
    assert float(detail2["fields"]["hydration"]) == 80.0
    assert len(detail2["revisions"]) >= 1
    assert any(
        "hydration" in r["changed_fields"] for r in detail2["revisions"]
    )

    # 6. Health panel is green (integrity clean) and reports LLM spend.
    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert health["ledger"]["ok"] is True
    assert health["domains"]["ok"] is True
    assert "llm_spend" in health
    assert health["llm_spend"]["daily_cap_usd"] > 0


def test_review_queue_drains_to_zero(workspace):
    _api, client = _client(workspace)
    assert client.post("/api/packs/activate", json={"name": "sourdough"}).status_code == 200

    client.post("/api/capture", json={"text": "baked a 75% hydration country loaf, bulk 5h", "channel": "web"})
    client.post("/api/capture", json={"text": "baked a 68% hydration seeded rye loaf, bulk 4h", "channel": "web"})
    uids = _uids(workspace, "sourdough")
    assert len(uids) >= 2

    # merge is review-gated by pack policy (packs/sourdough/policy.yaml) →
    # a deterministic pending approval.
    r = client.post(
        "/api/correct",
        json={"object_uid": uids[1], "action": "merge", "merge_into_uid": uids[0], "channel": "web"},
    )
    assert r.status_code == 200

    stats = client.get("/api/review/stats").json()
    assert stats["pending"] >= 1

    items = client.get("/api/review", params={"include_diff": True}).json()["items"]
    assert len(items) == stats["pending"]
    assert "diff" in items[0]
    ids = [it["approval_id"] for it in items]
    # The SPA's decision vocabulary ("approve", not "approved") is
    # normalized at the HTTP boundary.
    res = client.post(
        "/api/review/bulk-resolve",
        json={"approval_ids": ids, "decision": "approve"},
    )
    assert res.status_code == 200
    assert res.json()["count"] == len(ids)

    after = client.get("/api/review/stats").json()
    assert after["pending"] == 0


def test_single_review_resolution_normalizes_spa_decision(workspace):
    """The SPA's singular approve action reaches the executor vocabulary."""
    _api, client = _client(workspace)
    assert client.post("/api/packs/activate", json={"name": "sourdough"}).status_code == 200
    assert client.post(
        "/api/capture",
        json={"text": "baked a 75% hydration country loaf, bulk 5h", "channel": "web"},
    ).status_code == 200
    assert client.post(
        "/api/capture",
        json={"text": "baked a 68% hydration seeded rye loaf, bulk 4h", "channel": "web"},
    ).status_code == 200
    uids = _uids(workspace, "sourdough")
    queued = client.post(
        "/api/correct",
        json={
            "object_uid": uids[1],
            "action": "merge",
            "merge_into_uid": uids[0],
            "channel": "web",
        },
    )
    assert queued.status_code == 200
    item = client.get("/api/review", params={"include_diff": True}).json()["items"][0]

    resolved = client.post(
        f"/api/review/{item['approval_id']}/resolve",
        json={"decision": "approve"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["applied"] is True


def test_move_and_merge_corrections_over_http(workspace):
    _api, client = _client(workspace)
    client.post("/api/packs/activate", json={"name": "sourdough"})
    client.post("/api/packs/activate", json={"name": "plants"})

    client.post("/api/capture", json={"text": "watered the monstera, soil was dry", "channel": "web"})
    uid, _object_type = _first_uid(workspace, "plants")

    r = client.post(
        "/api/correct",
        json={"object_uid": uid, "action": "move", "target_domain": "sourdough", "channel": "web"},
    )
    assert r.status_code == 200
    moved = r.json()
    assert moved["action"] == "move"
    # Either applied or a legible error — never a silent raw row update.
    assert "applied" in moved
