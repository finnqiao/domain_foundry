"""Phase 6: Nominatim cache, GeoJSON projection, map block degrade path."""

from __future__ import annotations

import json
from pathlib import Path

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.geo.nominatim import GeocodeCache, NominatimClient, venue_query
from domain_foundry_core.paths import Workspace
from domain_foundry_core.projections.blockdata import BlockDataService
from domain_foundry_core.projections.geojson import (
    build_food_venues_collection,
    food_venues_path,
    row_to_feature,
)
from domain_foundry_core.security.store import connect_ro


def _ready_food(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("food")
    return api


def test_geocode_cache_hit(tmp_path: Path):
    calls: list[str] = []

    def fetch(url: str, headers: dict[str, str]) -> list[dict]:
        calls.append(url)
        return [
            {
                "lat": "34.4208",
                "lon": "-119.6982",
                "place_id": 12345,
                "display_name": "Discourse Coffee, Santa Barbara, CA",
            }
        ]

    cache = GeocodeCache(tmp_path / "cache")
    client = NominatimClient(cache, fetch=fetch, min_interval_s=0, sleep=lambda _s: None)

    first = client.geocode("Discourse Coffee, Santa Barbara")
    assert first.ok
    assert first.cached is False
    assert first.lat == 34.4208
    assert len(calls) == 1

    second = client.geocode("Discourse Coffee, Santa Barbara")
    assert second.ok
    assert second.cached is True
    assert second.place_name and "Discourse" in second.place_name
    assert len(calls) == 1  # cache hit — no second network call

    # Normalization: extra whitespace / case still hits same cache key.
    third = client.geocode("  discourse coffee, santa barbara  ")
    assert third.cached is True
    assert len(calls) == 1


def test_geojson_feature_shape_and_null_degrade(workspace: Workspace):
    api = _ready_food(workspace)

    with_geo = api.apply_operation(
        domain="food",
        operation="create",
        object_type="coffee_note",
        fields={
            "drink_name": "Flat white",
            "cafe_name": "Onibus Coffee",
            "city": "Tokyo",
            "lat": 35.644,
            "lng": 139.699,
            "place_name": "Onibus Coffee Nakameguro",
            "visited_at": "2026-07-01T10:00:00+00:00",
        },
        channel="test",
    )
    assert with_geo["ok"] is True

    without_geo = api.apply_operation(
        domain="food",
        operation="create",
        object_type="dining_note",
        fields={
            "restaurant": "Oriole",
            "city": "Chicago",
            "noted_at": "2026-07-02T19:00:00+00:00",
        },
        channel="test",
    )
    assert without_geo["ok"] is True

    pack = api.packs.get("food")
    assert pack is not None
    feature = row_to_feature(
        pack=pack,
        object_type="coffee_note",
        row={
            "object_uid": with_geo["object_uid"],
            "entry_id": None,
            "lat": 35.644,
            "lng": 139.699,
            "place_name": "Onibus Coffee Nakameguro",
            "cafe_name": "Onibus Coffee",
            "drink_name": "Flat white",
        },
    )
    assert feature is not None
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"
    assert feature["geometry"]["coordinates"] == [139.699, 35.644]
    assert feature["properties"]["object_type"] == "coffee_note"
    assert feature["properties"]["object_uid"] == with_geo["object_uid"]
    assert feature["properties"]["note_ref"] == with_geo["object_uid"]

    null_feature = row_to_feature(
        pack=pack,
        object_type="dining_note",
        row={
            "object_uid": without_geo["object_uid"],
            "lat": None,
            "lng": None,
            "restaurant": "Oriole",
        },
    )
    assert null_feature is None

    collection = build_food_venues_collection(workspace, registry=api.packs)
    assert collection["type"] == "FeatureCollection"
    assert collection["meta"]["feature_count"] == 1
    assert collection["meta"]["skipped_null_geo"] == 1
    assert len(collection["features"]) == 1

    # Drain geojson adapter → artifact on disk.
    report = api.drain_projections()
    assert report["failed_count"] == 0
    path = food_venues_path(workspace)
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["type"] == "FeatureCollection"
    assert on_disk["meta"]["feature_count"] == 1
    assert on_disk["features"][0]["properties"]["object_type"] == "coffee_note"


def test_map_block_nullable_geo_degrade(workspace: Workspace):
    api = _ready_food(workspace)
    api.apply_operation(
        domain="food",
        operation="create",
        object_type="coffee_note",
        fields={
            "drink_name": "Espresso",
            "cafe_name": "Discourse Coffee",
            "city": "Santa Barbara",
            "lat": 34.42,
            "lng": -119.70,
            "visited_at": "2026-07-03T09:00:00+00:00",
        },
        channel="test",
    )
    api.apply_operation(
        domain="food",
        operation="create",
        object_type="coffee_note",
        fields={
            "drink_name": "Pour over",
            "cafe_name": "Unknown Cafe",
            "city": "Nowhere",
            "visited_at": "2026-07-04T09:00:00+00:00",
        },
        channel="test",
    )

    svc = BlockDataService(workspace, registry=api.packs)
    data = svc.view_data("food", "map")
    assert data["block"] == "map"
    assert data["count"] == 1
    assert data["skipped_null_geo"] == 1
    assert data["scanned"] == 2
    assert len(data["rows"]) == 1
    assert data["rows"][0]["cafe_name"] == "Discourse Coffee"
    assert data["geojson"]["type"] == "FeatureCollection"
    assert len(data["geojson"]["features"]) == 1


def test_geocode_amend_via_correct_updates_domains(workspace: Workspace):
    api = _ready_food(workspace)
    created = api.apply_operation(
        domain="food",
        operation="create",
        object_type="dining_note",
        fields={
            "restaurant": "Kumiko",
            "city": "Chicago",
            "noted_at": "2026-07-05T20:00:00+00:00",
        },
        channel="test",
    )
    uid = created["object_uid"]
    assert uid

    corr = api.correct(
        object_uid=uid,
        action="amend",
        fields={
            "lat": 41.884,
            "lng": -87.651,
            "place_id": "999",
            "place_name": "Kumiko, Chicago",
        },
        channel="geocode_backfill",
    )
    assert corr["applied"] is True

    conn = connect_ro(workspace.domains_db)
    try:
        row = conn.execute(
            "SELECT lat, lng, place_id, place_name FROM food__dining_note WHERE object_uid = ?",
            (uid,),
        ).fetchone()
        assert row["lat"] == 41.884
        assert row["lng"] == -87.651
        assert row["place_id"] == "999"
        assert "Kumiko" in row["place_name"]
    finally:
        conn.close()

    api.drain_projections()
    collection = json.loads(food_venues_path(workspace).read_text(encoding="utf-8"))
    uids = {f["properties"]["object_uid"] for f in collection["features"]}
    assert uid in uids


def test_venue_query_builders():
    assert (
        venue_query("coffee_note", {"cafe_name": "Onibus", "city": "Tokyo"})
        == "Onibus, Tokyo"
    )
    assert venue_query("dining_note", {"restaurant": "Oriole"}) == "Oriole"
    assert venue_query("coffee_note", {"cafe_name": "", "city": "Tokyo"}) is None
    assert (
        venue_query(
            "dining_note",
            {
                "restaurant": "Oriole Chicago — Tasting Menu Date: 06/30/26 STANDARD",
                "city": "Chicago",
            },
        )
        == "Oriole Chicago, Chicago"
    )
