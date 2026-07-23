"""GeoJSON projection adapter — food/drink venue FeatureCollection artifact.

Rebuilds ``{home}/projections/food_venues.geojson`` whenever a food venue
object type drains. Rows without lat/lng are omitted (nullable-geo degrade).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from domain_foundry_core.clock import now_iso
from domain_foundry_core.geo.nominatim import VENUE_OBJECT_TYPES, venue_query
from domain_foundry_core.packs.models import DomainPack
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.packs.schema_compiler import table_name
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro

GEOJSON_ADAPTER = "geojson"
DEFAULT_GEOJSON_REL = "projections/food_venues.geojson"
FOOD_VENUE_DOMAIN = "food"


def food_venues_path(workspace: Workspace) -> Path:
    return workspace.home / DEFAULT_GEOJSON_REL


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _title_for(pack: DomainPack, object_type: str, row: dict[str, Any]) -> str:
    obj = pack.objects.get(object_type)
    if obj and obj.title_field:
        value = row.get(obj.title_field)
        if value is not None and str(value).strip():
            return str(value).strip()
    for key in ("place_name", "cafe_name", "restaurant", "place", "name", "producer"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return str(row.get("object_uid") or object_type)


def row_to_feature(
    *,
    pack: DomainPack,
    object_type: str,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a GeoJSON Point Feature, or None when lat/lng are missing/invalid."""
    lat_raw, lng_raw = row.get("lat"), row.get("lng")
    if lat_raw is None or lng_raw is None:
        return None
    try:
        lat = float(lat_raw)
        lng = float(lng_raw)
    except (TypeError, ValueError):
        return None
    uid = str(row.get("object_uid") or "")
    props: dict[str, Any] = {
        "object_type": object_type,
        "object_uid": uid,
        "entry_id": row.get("entry_id"),
        "title": _title_for(pack, object_type, row),
        "place_name": row.get("place_name"),
        "note_ref": uid or None,
        "venue_query": venue_query(object_type, row),
    }
    # Preserve useful venue labels without dumping every column.
    for key in ("cafe_name", "restaurant", "place", "city", "region", "producer", "name"):
        if row.get(key) is not None and str(row.get(key)).strip():
            props[key] = row.get(key)
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": props,
    }


def build_food_venues_collection(workspace: Workspace, *, registry: PackRegistry | None = None) -> dict[str, Any]:
    """Scan food venue tables and build a FeatureCollection (ungeocoded omitted)."""
    reg = registry or PackRegistry(workspace)
    pack = reg.get(FOOD_VENUE_DOMAIN)
    features: list[dict[str, Any]] = []
    scanned = 0
    skipped_null_geo = 0
    if pack is None or not workspace.domains_db.exists():
        return {
            "type": "FeatureCollection",
            "features": [],
            "meta": {
                "generated_at": now_iso(),
                "domain": FOOD_VENUE_DOMAIN,
                "scanned": 0,
                "skipped_null_geo": 0,
                "feature_count": 0,
            },
        }

    conn = connect_ro(workspace.domains_db)
    try:
        for object_type in VENUE_OBJECT_TYPES:
            if object_type not in pack.objects:
                continue
            tname = table_name(pack.name, object_type)
            try:
                rows = conn.execute(
                    f"SELECT * FROM {tname} WHERE tombstoned = 0 ORDER BY created_at ASC"
                ).fetchall()
            except Exception:
                continue
            for raw in rows:
                scanned += 1
                row = {k: raw[k] for k in raw.keys()}
                feature = row_to_feature(pack=pack, object_type=object_type, row=row)
                if feature is None:
                    skipped_null_geo += 1
                    continue
                features.append(feature)
    finally:
        conn.close()

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "generated_at": now_iso(),
            "domain": FOOD_VENUE_DOMAIN,
            "scanned": scanned,
            "skipped_null_geo": skipped_null_geo,
            "feature_count": len(features),
        },
    }


class GeoJsonAdapter:
    """Projection adapter that materializes the food venues GeoJSON artifact."""

    name = GEOJSON_ADAPTER

    def __init__(
        self,
        workspace: Workspace,
        *,
        registry: PackRegistry | None = None,
        artifact_path: Path | None = None,
    ) -> None:
        self.ws = workspace
        self.registry = registry or PackRegistry(workspace)
        self.artifact_path = Path(artifact_path) if artifact_path else food_venues_path(workspace)

    def render(self, object_key: str, outbox_row: dict[str, Any]) -> dict[str, Any]:
        domain, _, object_type = object_key.partition(":")
        if domain != FOOD_VENUE_DOMAIN:
            return {"status": "skipped", "reason": f"non-food object_key {object_key!r}"}
        if object_type and object_type not in VENUE_OBJECT_TYPES and object_type != "*":
            # Non-venue food objects still trigger a rebuild so meta stays fresh,
            # but we can skip when the pack has no venue tables yet.
            pack = self.registry.get(FOOD_VENUE_DOMAIN)
            if pack is None:
                return {"status": "skipped", "reason": "food pack inactive"}

        collection = build_food_venues_collection(self.ws, registry=self.registry)
        _atomic_write_json(self.artifact_path, collection)
        meta = collection.get("meta") or {}
        return {
            "status": "rendered",
            "path": str(self.artifact_path.relative_to(self.ws.home)),
            "feature_count": int(meta.get("feature_count") or 0),
            "skipped_null_geo": int(meta.get("skipped_null_geo") or 0),
            "scanned": int(meta.get("scanned") or 0),
        }
