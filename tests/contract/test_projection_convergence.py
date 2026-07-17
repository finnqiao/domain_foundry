"""P4 gate: kill-the-daemon projection convergence.

Canonical commit with projections "down" → restart → projections converge,
watermark advances, receipt flips from pending to refreshed.
"""

from __future__ import annotations

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.router import Router
from domain_foundry_core.security.store import connect_ro


def _ready(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.packs.activate_bundled("plants")
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    return api


def _change_request_ids(workspace: Workspace, entry_id: str) -> list[int]:
    conn = connect_ro(workspace.ledger_db)
    try:
        return [
            int(r["id"])
            for r in conn.execute(
                "SELECT id FROM change_request WHERE entry_id = ?", (entry_id,)
            ).fetchall()
        ]
    finally:
        conn.close()


def test_kill_the_daemon_convergence(workspace: Workspace):
    api = _ready(workspace)

    # Canonical commit while the drain loop is NOT running (daemon down).
    receipt = api.capture(
        "baked a 75% hydration country loaf, bulk 5h, came out great",
        channel="cli",
        source_ref="conv-1",
    )
    assert receipt.status == "applied"
    assert receipt.projection_status == "pending"

    cr_ids = _change_request_ids(workspace, receipt.entry_id)
    assert cr_ids

    # Outbox has pending work; no watermark yet.
    conn = connect_ro(workspace.ledger_db)
    try:
        pending = conn.execute(
            "SELECT adapter, status FROM projection_outbox WHERE change_request_id = ?",
            (cr_ids[0],),
        ).fetchall()
        assert {r["adapter"] for r in pending} == {"app_feed", "markdown"}
        assert all(r["status"] == "pending" for r in pending)
        wm = conn.execute("SELECT COUNT(*) AS n FROM projection_watermark").fetchone()
        assert wm["n"] == 0
    finally:
        conn.close()

    before = api.projection_status(entry_id=receipt.entry_id)
    assert before["projection_status"] == "pending"

    # ---- Restart: brand-new process/coordinator recovers from durable state ----
    restarted = HarnessAPI(workspace.home)
    report = restarted.drain_projections()
    assert report["failed_count"] == 0
    assert report["drained_count"] >= 2

    conn = connect_ro(workspace.ledger_db)
    try:
        rows = conn.execute(
            "SELECT adapter, status, watermark FROM projection_outbox "
            "WHERE change_request_id = ?",
            (cr_ids[0],),
        ).fetchall()
        assert all(r["status"] == "done" for r in rows)
        assert all(r["watermark"] is not None for r in rows)
        wms = conn.execute(
            "SELECT adapter, watermark FROM projection_watermark"
        ).fetchall()
        assert {r["adapter"] for r in wms} == {"app_feed", "markdown"}
        first_watermarks = {r["adapter"]: int(r["watermark"]) for r in wms}
    finally:
        conn.close()

    # Receipt flips to refreshed after convergence.
    after = restarted.projection_status(entry_id=receipt.entry_id)
    assert after["projection_status"] == "refreshed"

    # Managed markdown note materialized into the generic vault.
    note = (
        workspace.vault_dir
        / "Sourdough"
        / "bake"
        / "country-loaf.md"
    )
    # Title-derived slug may vary; assert at least one note exists under the folder.
    bake_notes = list((workspace.vault_dir / "Sourdough" / "bake").glob("*.md"))
    assert bake_notes, f"expected a rendered bake note (looked for {note})"
    body = bake_notes[0].read_text(encoding="utf-8")
    assert "%%managed:start" in body
    assert "Hydration" in body

    # ---- Watermark advances on the next commit ----
    receipt2 = api.capture(
        "baked an 80% hydration batard, bulk 4h, came out good",
        channel="cli",
        source_ref="conv-2",
    )
    assert receipt2.status == "applied"
    restarted.drain_projections()
    conn = connect_ro(workspace.ledger_db)
    try:
        wms = conn.execute(
            "SELECT adapter, watermark FROM projection_watermark"
        ).fetchall()
        second_watermarks = {r["adapter"]: int(r["watermark"]) for r in wms}
    finally:
        conn.close()
    for adapter, wm in second_watermarks.items():
        assert wm > first_watermarks[adapter], f"watermark for {adapter} did not advance"


def test_failed_projection_stays_pending_and_retries(workspace: Workspace):
    """A failing adapter leaves the outbox row retryable; recovery drains it."""
    from domain_foundry_core.projections.coordinator import ProjectionCoordinator

    api = _ready(workspace)
    api.capture("baked a rye boule", channel="cli", source_ref="retry-1")

    class _BoomAdapter:
        name = "app_feed"
        calls = 0

        def render(self, object_key, outbox_row):
            _BoomAdapter.calls += 1
            raise RuntimeError("projection backend down")

    boom = _BoomAdapter()
    coord = ProjectionCoordinator(
        workspace, registry=api.packs, adapters={"app_feed": boom}
    )
    report = coord.drain(adapters=["app_feed"])
    assert report.failed_count >= 1
    assert report.drained_count == 0

    conn = connect_ro(workspace.ledger_db)
    try:
        row = conn.execute(
            "SELECT status, attempts, last_error FROM projection_outbox "
            "WHERE adapter = 'app_feed' ORDER BY id LIMIT 1"
        ).fetchone()
        assert row["status"] == "failed"
        assert row["attempts"] >= 1
        assert "down" in (row["last_error"] or "")
    finally:
        conn.close()

    # Recovery with a healthy adapter drains the still-pending work.
    healthy = ProjectionCoordinator(workspace, registry=api.packs)
    ok = healthy.drain(adapters=["app_feed"])
    assert ok.drained_count >= 1
