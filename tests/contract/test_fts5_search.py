"""Phase 2 FTS5 substrate (G8): index sync, search hits, idempotent triggers."""

from __future__ import annotations

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.router import Router
from domain_foundry_core.security.store import connect_ro, connect_rw


def _ready(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    return api


def test_capture_indexes_entry_raw_text(workspace: Workspace):
    api = _ready(workspace)
    receipt = api.capture(
        "tasting notes for junmai sake at the bar",
        channel="cli",
        source_ref="fts-cap-1",
    )

    conn = connect_ro(workspace.ledger_db)
    try:
        docs = conn.execute(
            "SELECT kind, ref_id, raw_text FROM search_document WHERE kind = 'entry'"
        ).fetchall()
        assert len(docs) == 1
        assert docs[0]["ref_id"] == receipt.entry_id
        assert "sake" in (docs[0]["raw_text"] or "").lower()

        fts_rows = conn.execute(
            """
            SELECT sd.ref_id, sd.raw_text
            FROM search_fts
            JOIN search_document sd ON sd.id = search_fts.rowid
            WHERE sd.kind = 'entry' AND search_fts MATCH 'sake'
            """
        ).fetchall()
        assert len(fts_rows) == 1
        assert fts_rows[0]["ref_id"] == receipt.entry_id
    finally:
        conn.close()

    result = api.search("sake")
    assert result["total"] >= 1
    assert any(h["ref_id"] == receipt.entry_id and h["kind"] == "entry" for h in result["hits"])


def test_apply_indexes_canonical_text(workspace: Workspace):
    api = _ready(workspace)
    receipt = api.capture(
        "baked a rye boule at 75% hydration",
        channel="cli",
        source_ref="fts-apply-1",
    )
    assert receipt.status == "applied"

    conn = connect_ro(workspace.ledger_db)
    try:
        row = conn.execute(
            """
            SELECT uid, searchable_text FROM canonical_object
            WHERE domain = 'sourdough' AND status = 'active'
            """
        ).fetchone()
        assert row is not None
        blob = (row["searchable_text"] or "").lower()
        assert "rye" in blob or "75" in blob or "hydration" in blob

        docs = conn.execute(
            """
            SELECT ref_id, canonical_text FROM search_document
            WHERE kind = 'canonical' AND ref_id = ?
            """,
            (row["uid"],),
        ).fetchone()
        assert docs is not None
        assert docs["canonical_text"]
    finally:
        conn.close()

    result = api.search("rye", kind="canonical", domain="sourdough")
    assert result["total"] >= 1
    assert any(h["kind"] == "canonical" for h in result["hits"])


def test_search_returns_known_fixture_objects(workspace: Workspace):
    api = _ready(workspace)
    api.capture("fed the rye starter this morning", channel="cli", source_ref="fts-fx-1")
    api.capture("baked an 80% hydration batard", channel="cli", source_ref="fts-fx-2")

    by_starter = api.search("starter", domain="sourdough")
    assert by_starter["total"] >= 1
    assert any("starter" in ((h.get("raw_text") or "") + (h.get("canonical_text") or "")).lower()
               for h in by_starter["hits"])

    by_hydration = api.search("hydration", kind="canonical")
    assert by_hydration["total"] >= 1
    assert all(h["kind"] == "canonical" for h in by_hydration["hits"])


def test_fts_triggers_are_idempotent(workspace: Workspace):
    api = _ready(workspace)
    receipt = api.capture(
        "idempotent sake indexing probe",
        channel="cli",
        source_ref="fts-idem-1",
    )

    conn = connect_rw(workspace.ledger_db)
    try:
        before = conn.execute(
            "SELECT COUNT(*) AS n FROM search_document WHERE kind = 'entry' AND ref_id = ?",
            (receipt.entry_id,),
        ).fetchone()["n"]
        assert before == 1

        # Re-fire the entry UPDATE trigger path (same values) — must not duplicate.
        conn.execute(
            """
            UPDATE entry SET summary = summary, domain = domain, updated_at = updated_at
            WHERE id = ?
            """,
            (receipt.entry_id,),
        )
        conn.commit()

        after = conn.execute(
            "SELECT COUNT(*) AS n FROM search_document WHERE kind = 'entry' AND ref_id = ?",
            (receipt.entry_id,),
        ).fetchone()["n"]
        assert after == 1

        # Re-upsert searchable_text on a canonical row if present.
        co = conn.execute(
            "SELECT uid, searchable_text FROM canonical_object LIMIT 1"
        ).fetchone()
        if co:
            conn.execute(
                """
                UPDATE canonical_object
                SET searchable_text = ?, updated_at = updated_at
                WHERE uid = ?
                """,
                (co["searchable_text"], co["uid"]),
            )
            conn.commit()
            canon_n = conn.execute(
                """
                SELECT COUNT(*) AS n FROM search_document
                WHERE kind = 'canonical' AND ref_id = ?
                """,
                (co["uid"],),
            ).fetchone()["n"]
            assert canon_n == 1
    finally:
        conn.close()
