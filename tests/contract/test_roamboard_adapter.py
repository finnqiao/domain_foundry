"""Phase 7 Roamboard sync adapter — fixture contracts (no live Supabase)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro
from domain_foundry_roamboard.mapper import (
    feed_to_records,
    mapping_config_dict,
    source_ref_item,
    source_ref_trip,
)
from domain_foundry_roamboard.remote import live_creds_present
from domain_foundry_roamboard.shapes import load_feed, load_patch_bundle
from domain_foundry_roamboard.shadow import run_shadow
from domain_foundry_roamboard.sync import SyncMode, sync_roamboard

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures" / "roamboard"
FEED = FIXTURES / "feed.json"
PATCH = FIXTURES / "patch_bundle.json"


def _ready_travel(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("travel")
    return api


def test_feed_fixture_maps_to_roamboard_source_refs():
    feed = load_feed(FEED)
    records = feed_to_records(feed)
    assert len(records["trip"]) == 2
    assert len(records["timeline_item"]) == 3
    assert len(records["event_log"]) == 2
    assert records["trip"][0]["id"] == "port-city-weekend"
    assert source_ref_trip("port-city-weekend") == "roamboard:trip:port-city-weekend"
    assert source_ref_item("10") == "roamboard:timeline_item:10"
    harbor = next(r for r in records["timeline_item"] if r["id"] == "10")
    assert harbor["title"] == "Harbor walking tour"
    assert float(harbor["lat"]) == 41.88
    assert float(harbor["lng"]) == -87.63


def test_mapping_config_declares_roamboard_channel():
    raw = mapping_config_dict()
    assert raw["channel"] == "roamboard"
    refs = {e["name"]: e["source_ref_template"] for e in raw["entities"]}
    assert refs["trip"] == "roamboard:trip:{id}"
    assert refs["timeline_item"] == "roamboard:timeline_item:{id}"
    assert refs["event_log"] == "roamboard:event:{id}"


def test_dry_run_feed_accounts_for_fixture(workspace: Workspace):
    _ready_travel(workspace)
    report = sync_roamboard(workspace.home, mode=SyncMode.DRY_RUN, feed=FEED)
    assert report.dry_run is True
    assert report.applied is False
    imp = report.import_report or {}
    # 2 trips + 3 items + 2 synthetic feed events
    assert imp["source_total"] == 7
    assert imp["would_import"] == 7
    assert imp["imported"] == 0
    assert imp["complete"] is True
    assert imp["by_entity"]["trip"]["would_import"] == 2
    assert imp["by_entity"]["timeline_item"]["would_import"] == 3


def test_apply_feed_is_idempotent_and_preserves_geo(workspace: Workspace):
    _ready_travel(workspace)
    first = sync_roamboard(workspace.home, mode=SyncMode.APPLY, feed=FEED, write_shadow=False)
    assert first.applied is True
    assert (first.import_report or {})["imported"] == 7

    second = sync_roamboard(workspace.home, mode=SyncMode.APPLY, feed=FEED, write_shadow=False)
    assert (second.import_report or {})["imported"] == 0
    assert (second.import_report or {})["skipped_existing"] == 7

    conn = connect_ro(workspace.ledger_db)
    try:
        row = conn.execute(
            "SELECT source_ref FROM capture_event WHERE source_ref = ?",
            ("roamboard:timeline_item:10",),
        ).fetchone()
        assert row is not None
    finally:
        conn.close()

    dconn = connect_ro(workspace.domains_db)
    try:
        item = dconn.execute(
            "SELECT title, lat, lng, location_name FROM travel__timeline_item "
            "WHERE title = ?",
            ("Harbor walking tour",),
        ).fetchone()
        assert item is not None
        assert float(item["lat"]) == 41.88
        assert float(item["lng"]) == -87.63
        assert item["location_name"] == "Old Harbor"
        trip = dconn.execute(
            "SELECT slug, name FROM travel__trip WHERE slug = ?",
            ("port-city-weekend",),
        ).fetchone()
        assert trip is not None
        assert trip["name"] == "Port City weekend"
    finally:
        dconn.close()


def test_patch_bundle_writes_roamboard_patch_events(workspace: Workspace):
    _ready_travel(workspace)
    bundle = load_patch_bundle(PATCH)
    assert len(bundle["updates"]) == 2
    report = sync_roamboard(
        workspace.home,
        mode=SyncMode.APPLY,
        patch_bundle=PATCH,
        write_shadow=False,
    )
    # 1 trip stub + 2 patch events
    assert (report.import_report or {})["imported"] == 3
    conn = connect_ro(workspace.ledger_db)
    try:
        refs = {
            r["source_ref"]
            for r in conn.execute(
                "SELECT source_ref FROM capture_event WHERE channel = 'roamboard'"
            )
        }
    finally:
        conn.close()
    assert "roamboard:trip:port-city-weekend" in refs
    assert "roamboard:patch:upd-mark-booked-1" in refs
    assert "roamboard:patch:upd-add-note-1" in refs


def test_shadow_writes_report_dir_without_mutating_travel_db(
    workspace: Workspace, tmp_path: Path
):
    _ready_travel(workspace)
    # Synthetic private travel.sqlite (stand-in for HermesWorkspace travel DB).
    travel_db = tmp_path / "travel.sqlite"
    conn = sqlite3.connect(str(travel_db))
    try:
        conn.executescript(
            """
            CREATE TABLE trips (
              id INTEGER PRIMARY KEY,
              slug TEXT,
              name TEXT,
              status TEXT,
              start_date TEXT,
              end_date TEXT
            );
            CREATE TABLE timeline_items (id INTEGER PRIMARY KEY);
            CREATE TABLE event_log (id INTEGER PRIMARY KEY);
            INSERT INTO trips(id, slug, name, status, start_date, end_date)
            VALUES (1, 'port-city-weekend', 'Port City weekend', 'planning',
                    '2026-03-10', '2026-03-12');
            INSERT INTO timeline_items(id) VALUES (10), (11);
            INSERT INTO event_log(id) VALUES (100);
            """
        )
        conn.commit()
    finally:
        conn.close()

    before = travel_db.read_bytes()
    sync_roamboard(
        workspace.home,
        mode=SyncMode.APPLY,
        feed=FEED,
        write_shadow=False,
    )
    shadow = run_shadow(workspace.home, travel_db=travel_db, write=True)
    after = travel_db.read_bytes()
    assert before == after, "shadow must not mutate travel.sqlite"

    assert shadow.report_dir is not None
    report_dir = Path(shadow.report_dir)
    assert (report_dir / "diff.json").exists()
    assert (report_dir / "SUMMARY.md").exists()
    assert report_dir.parent.name == "roamboard"
    assert report_dir.parent.parent.name == "shadow"

    payload = json.loads((report_dir / "diff.json").read_text(encoding="utf-8"))
    assert payload["private"]["trips"] == 1
    assert payload["foundry"]["trips"] == 2
    assert "port-city-weekend" not in payload["trip_slug_only_private"]
    assert "river-station" in payload["trip_slug_only_foundry"]


def test_shadow_cli_mode_embeds_shadow_payload(workspace: Workspace, tmp_path: Path):
    _ready_travel(workspace)
    travel_db = tmp_path / "empty-travel.sqlite"
    conn = sqlite3.connect(str(travel_db))
    try:
        conn.executescript(
            """
            CREATE TABLE trips(id INTEGER);
            CREATE TABLE timeline_items(id INTEGER);
            CREATE TABLE event_log(id INTEGER);
            """
        )
        conn.commit()
    finally:
        conn.close()

    report = sync_roamboard(
        workspace.home,
        mode=SyncMode.SHADOW,
        feed=FEED,
        travel_db=travel_db,
    )
    assert report.mode == "shadow"
    assert report.dry_run is True
    assert report.shadow is not None
    assert report.shadow.get("report_dir")


@pytest.mark.skipif(
    not live_creds_present(),
    reason="ROAMBOARD_SYNC_TOKEN or ROAMBOARD_SUPABASE_* not set",
)
def test_live_pending_patches_smoke():
    """Opt-in live smoke — skipped in CI / default local runs without creds."""
    from domain_foundry_roamboard.remote import fetch_pending_patches

    bundles = fetch_pending_patches()
    assert isinstance(bundles, list)
