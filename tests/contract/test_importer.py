"""Phase 2 generic importer — fixture-tested provenance + idempotency."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.migrations.importers import (
    DictSource,
    FixtureSource,
    GenericImporter,
    SqliteTableSource,
    load_mapping,
)
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro, connect_rw

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures" / "importers"
EXAMPLES = REPO.parent / "examples" / "importers"


def _ready_japanese(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("japanese")
    return api


def _ready_plants(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("plants")
    return api


def test_load_mapping_japanese_example():
    mapping = load_mapping(EXAMPLES / "japanese_vocab.yaml")
    assert mapping.name == "hermes-japanese-vocab-fixture"
    assert mapping.channel == "hermes-import"
    assert len(mapping.entities) == 2
    assert mapping.entities[0].source_ref_template == "hermes:personal:jp_vocab:{id}"


def test_dry_run_accounts_for_all_fixture_rows(workspace: Workspace):
    _ready_japanese(workspace)
    mapping = load_mapping(EXAMPLES / "japanese_vocab.yaml")
    source = FixtureSource(FIXTURES / "japanese")
    report = GenericImporter(workspace, mapping, dry_run=True).run(source)

    # 3 vocab (1 invalid) + 2 grammar
    assert report.source_total == 5
    assert report.would_import == 4
    assert report.skipped_invalid == 1
    assert report.imported == 0
    assert report.complete
    assert "missing required fields: word" in (
        next(o.reason for o in report.outcomes if o.kind == "skipped_invalid") or ""
    )


def test_apply_preserves_timestamps_and_source_ref(workspace: Workspace):
    _ready_japanese(workspace)
    mapping = load_mapping(EXAMPLES / "japanese_vocab.yaml")
    source = FixtureSource(FIXTURES / "japanese")
    report = GenericImporter(workspace, mapping, dry_run=False).run(source)

    assert report.imported == 4
    assert report.skipped_invalid == 1
    assert report.complete

    conn = connect_ro(workspace.ledger_db)
    try:
        row = conn.execute(
            """
            SELECT c.source_ref, c.captured_at, c.created_at, c.raw_text,
                   e.status, e.domain, e.object_type, e.created_at AS entry_created
            FROM capture_event c
            JOIN entry e ON e.capture_event_id = c.id
            WHERE c.source_ref = ?
            """,
            ("hermes:personal:jp_vocab:1",),
        ).fetchone()
        assert row is not None
        assert row["source_ref"] == "hermes:personal:jp_vocab:1"
        assert row["captured_at"] == "2025-11-02T09:15:00+00:00"
        assert row["created_at"] == "2025-11-02T09:15:00+00:00"
        assert row["entry_created"] == "2025-11-02T09:15:00+00:00"
        assert row["status"] == "applied"
        assert row["domain"] == "japanese"
        assert row["object_type"] == "jp_vocab"
        assert "水" in row["raw_text"]

        canon = conn.execute(
            """
            SELECT co.uid, co.created_at, co.updated_at, co.searchable_text
            FROM canonical_object co
            JOIN source_link sl
              ON sl.target_type = 'canonical_object' AND sl.target_id = co.uid
            WHERE sl.source_type = 'import'
              AND sl.source_id = ?
            """,
            ("hermes:personal:jp_vocab:1",),
        ).fetchone()
        assert canon is not None
        assert canon["created_at"] == "2025-11-02T09:15:00+00:00"
        assert canon["updated_at"] == "2026-01-10T12:00:00+00:00"
        assert "水" in (canon["searchable_text"] or "")
        object_uid = canon["uid"]
    finally:
        conn.close()

    dconn = connect_ro(workspace.domains_db)
    try:
        drow = dconn.execute(
            "SELECT * FROM japanese__jp_vocab WHERE object_uid = ?",
            (object_uid,),
        ).fetchone()
        assert drow is not None
        assert drow["word"] == "水"
        assert drow["reading"] == "みず"
        assert float(drow["ease_factor"]) == 2.5
        assert drow["created_at"] == "2025-11-02T09:15:00+00:00"
        assert drow["updated_at"] == "2026-01-10T12:00:00+00:00"
    finally:
        dconn.close()


def test_re_run_is_noop_idempotent(workspace: Workspace):
    _ready_japanese(workspace)
    mapping = load_mapping(EXAMPLES / "japanese_vocab.yaml")
    source = FixtureSource(FIXTURES / "japanese")
    first = GenericImporter(workspace, mapping, dry_run=False).run(source)
    second = GenericImporter(workspace, mapping, dry_run=False).run(source)

    assert first.imported == 4
    assert second.imported == 0
    assert second.skipped_existing == 4
    assert second.skipped_invalid == 1
    assert second.complete

    conn = connect_ro(workspace.ledger_db)
    try:
        captures = conn.execute(
            "SELECT COUNT(*) AS n FROM capture_event WHERE channel = ?",
            ("hermes-import",),
        ).fetchone()["n"]
        objects = conn.execute(
            "SELECT COUNT(*) AS n FROM canonical_object WHERE domain = ?",
            ("japanese",),
        ).fetchone()["n"]
    finally:
        conn.close()
    assert captures == 4
    assert objects == 4


def test_logbook_entry_source_ref_shape(workspace: Workspace):
    _ready_plants(workspace)
    mapping = load_mapping(EXAMPLES / "logbook_entry.yaml")
    source = FixtureSource(FIXTURES / "entries.jsonl")
    report = GenericImporter(workspace, mapping, dry_run=False).run(source)
    assert report.imported == 2
    assert report.complete

    conn = connect_ro(workspace.ledger_db)
    try:
        refs = {
            r[0]
            for r in conn.execute(
                "SELECT source_ref FROM capture_event WHERE channel = ?",
                ("hermes-import",),
            ).fetchall()
        }
    finally:
        conn.close()
    assert refs == {"hermes:logbook:entry:143", "hermes:logbook:entry:144"}


def test_reconciliation_markdown_and_dict(workspace: Workspace):
    _ready_japanese(workspace)
    mapping = load_mapping(EXAMPLES / "japanese_vocab.yaml")
    source = FixtureSource(FIXTURES / "japanese")
    report = GenericImporter(workspace, mapping, dry_run=True).run(source)
    payload = report.to_dict()
    assert payload["complete"] is True
    assert payload["source_total"] == 5
    md = report.to_markdown()
    assert "Reconciliation" in md
    assert "jp_vocab" in md


def test_sqlite_table_source_readonly(workspace: Workspace, tmp_path: Path):
    """Generic RO sqlite driver (not Hermes) feeds the importer."""
    _ready_plants(workspace)
    src_db = tmp_path / "source.sqlite"
    conn = sqlite3.connect(str(src_db))
    try:
        conn.execute(
            "CREATE TABLE entries (id INTEGER PRIMARY KEY, text TEXT, "
            "plant_name TEXT, action TEXT, created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO entries VALUES (7, 'repotted ficus', 'ficus', 'repot', "
            "'2024-01-01T00:00:00+00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    mapping = load_mapping(EXAMPLES / "logbook_entry.yaml")
    source = SqliteTableSource(src_db, tables={"entries": "entries"})
    report = GenericImporter(workspace, mapping, dry_run=False).run(source)
    assert report.imported == 1
    assert report.complete

    # Prove source was opened RO by still being readable and unchanged.
    ro = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    try:
        assert ro.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 1
    finally:
        ro.close()


def test_dict_source_unit_path(workspace: Workspace):
    _ready_plants(workspace)
    mapping = load_mapping(EXAMPLES / "logbook_entry.yaml")
    source = DictSource(
        {
            "entries": [
                {
                    "id": 99,
                    "text": "observed orchid bloom",
                    "plant_name": "orchid",
                    "action": "observe",
                    "created_at": "2023-05-05T12:00:00+00:00",
                }
            ]
        }
    )
    report = GenericImporter(workspace, mapping, dry_run=False).run(source)
    assert report.imported == 1
    conn = connect_rw(workspace.ledger_db)
    try:
        row = conn.execute(
            "SELECT captured_at FROM capture_event WHERE source_ref = ?",
            ("hermes:logbook:entry:99",),
        ).fetchone()
        assert row["captured_at"] == "2023-05-05T12:00:00+00:00"
    finally:
        conn.close()


def _ready_travel(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("travel")
    return api


def test_load_mapping_travel_example():
    mapping = load_mapping(EXAMPLES / "travel.yaml")
    assert mapping.name == "hermes-travel-fixture"
    assert mapping.channel == "hermes-import"
    assert {e.name for e in mapping.entities} == {"trip", "timeline_item", "event_log"}
    assert mapping.entities[0].source_ref_template == "hermes:travel:trip:{id}"


def test_travel_dry_run_accounts_for_fixture_rows(workspace: Workspace):
    _ready_travel(workspace)
    mapping = load_mapping(EXAMPLES / "travel.yaml")
    source = FixtureSource(FIXTURES / "travel")
    report = GenericImporter(workspace, mapping, dry_run=True).run(source)

    # 3 trips (1 invalid) + 3 timeline_items + 3 event_log
    assert report.source_total == 9
    assert report.would_import == 8
    assert report.skipped_invalid == 1
    assert report.imported == 0
    assert report.complete
    assert report.by_entity["trip"]["would_import"] == 2
    assert report.by_entity["trip"]["skipped_invalid"] == 1
    assert report.by_entity["timeline_item"]["would_import"] == 3
    assert report.by_entity["event_log"]["would_import"] == 3


def test_travel_apply_preserves_geo_and_source_ref(workspace: Workspace):
    _ready_travel(workspace)
    mapping = load_mapping(EXAMPLES / "travel.yaml")
    source = FixtureSource(FIXTURES / "travel")
    report = GenericImporter(workspace, mapping, dry_run=False).run(source)

    assert report.imported == 8
    assert report.skipped_invalid == 1
    assert report.complete

    conn = connect_ro(workspace.ledger_db)
    try:
        canon = conn.execute(
            """
            SELECT co.uid
            FROM canonical_object co
            JOIN source_link sl
              ON sl.target_type = 'canonical_object' AND sl.target_id = co.uid
            WHERE sl.source_type = 'import'
              AND sl.source_id = ?
            """,
            ("hermes:travel:timeline_item:10",),
        ).fetchone()
        assert canon is not None
        object_uid = canon["uid"]
    finally:
        conn.close()

    dconn = connect_ro(workspace.domains_db)
    try:
        drow = dconn.execute(
            "SELECT * FROM travel__timeline_item WHERE object_uid = ?",
            (object_uid,),
        ).fetchone()
        assert drow is not None
        assert drow["title"] == "Harbor walking tour"
        assert float(drow["lat"]) == 41.88
        assert float(drow["lng"]) == -87.63
        assert drow["location"] == "Old Harbor"
        assert drow["created_at"] == "2026-01-06T11:00:00+00:00"
    finally:
        dconn.close()
