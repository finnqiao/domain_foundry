"""Roamboard sync engine — dry-run / apply / shadow against in-process HarnessAPI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.migrations.importers import (
    DictSource,
    GenericImporter,
    MappingConfig,
)
from domain_foundry_core.paths import Workspace

from domain_foundry_roamboard.mapper import (
    feed_to_records,
    mapping_config_dict,
    patch_bundle_to_records,
)
from domain_foundry_roamboard.shapes import load_feed, load_patch_bundle
from domain_foundry_roamboard.shadow import ShadowReport, run_shadow


class SyncMode(str, Enum):
    DRY_RUN = "dry_run"
    APPLY = "apply"
    SHADOW = "shadow"


@dataclass
class SyncReport:
    mode: str
    dry_run: bool
    applied: bool
    source: str | None = None
    import_report: dict[str, Any] | None = None
    shadow: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mapping_from_dict(raw: dict[str, Any]) -> MappingConfig:
    return MappingConfig.model_validate(raw)


def _patch_mapping() -> MappingConfig:
    """Like feed mapping, but event_log source_ref is ``roamboard:patch:{id}``."""
    raw = mapping_config_dict()
    for entity in raw["entities"]:
        if entity["name"] == "event_log":
            entity["source_ref_template"] = "roamboard:patch:{id}"
    return _mapping_from_dict(raw)


def _ready_api(home: Path) -> HarnessAPI:
    ws = Workspace(home)
    ws.ensure_layout()
    api = HarnessAPI(ws.home)
    api.init()
    try:
        api.packs.activate_bundled("travel")
    except Exception:
        pass
    return api


def sync_roamboard(
    home: Path | str,
    *,
    mode: SyncMode | str = SyncMode.DRY_RUN,
    feed: Path | str | None = None,
    patch_bundle: Path | str | None = None,
    travel_db: Path | str | None = None,
    records: dict[str, list[dict[str, Any]]] | None = None,
    write_shadow: bool = True,
) -> SyncReport:
    """Import Roamboard shapes into DF travel objects (idempotent on source_ref).

    Modes:
    - ``dry_run`` (default): reconcile without writing
    - ``apply``: write via GenericImporter → ledger + travel tables
    - ``shadow``: dry-run import accounting + write shadow/roamboard/ report
      comparing private travel.sqlite (RO) vs DF query
    """
    home_path = Path(home).expanduser().resolve()
    mode_enum = SyncMode(mode) if not isinstance(mode, SyncMode) else mode
    dry_run = mode_enum != SyncMode.APPLY
    applied = mode_enum == SyncMode.APPLY

    notes = [
        "In-process HarnessAPI (no HTTP hop).",
        "source_ref shape: roamboard:trip:… / roamboard:timeline_item:… / "
        "roamboard:event:… / roamboard:patch:…",
        "Never mutates travel/data/travel.sqlite.",
        "Does not disable or rewrite Roamboard launchd agents.",
    ]

    api = _ready_api(home_path)
    ws = Workspace(home_path)

    source_label: str | None = None
    entity_records: dict[str, list[dict[str, Any]]]
    mapping: MappingConfig

    if records is not None:
        entity_records = records
        mapping = _mapping_from_dict(mapping_config_dict())
        source_label = "inline-records"
    elif patch_bundle is not None:
        bundle = load_patch_bundle(patch_bundle)
        entity_records = patch_bundle_to_records(bundle)
        mapping = _patch_mapping()
        source_label = str(Path(patch_bundle).expanduser())
    elif feed is not None:
        feed_payload = load_feed(feed)
        entity_records = feed_to_records(feed_payload)
        mapping = _mapping_from_dict(mapping_config_dict())
        source_label = str(Path(feed).expanduser())
    else:
        raise ValueError("provide --feed, --patch-bundle, or inline records")

    importer = GenericImporter(ws, mapping, dry_run=dry_run)
    recon = importer.run(DictSource(entity_records))
    import_payload = recon.to_dict() if hasattr(recon, "to_dict") else _recon_dict(recon)

    shadow_payload: dict[str, Any] | None = None
    if mode_enum == SyncMode.SHADOW or (mode_enum == SyncMode.APPLY and write_shadow):
        # After apply, shadow compares; for pure --shadow, still write the report
        # even when DF is empty (documents the baseline gap).
        shadow: ShadowReport = run_shadow(
            home_path, travel_db=travel_db, write=write_shadow
        )
        shadow_payload = shadow.to_dict()
        if shadow.report_dir:
            notes.append(f"shadow report: {shadow.report_dir}")

    # Ensure api was used (keeps pack schemas warm); silence unused in dry paths.
    _ = api.health_panel() if hasattr(api, "health_panel") else None

    return SyncReport(
        mode=mode_enum.value,
        dry_run=dry_run,
        applied=applied and not dry_run,
        source=source_label,
        import_report=import_payload,
        shadow=shadow_payload,
        notes=notes,
    )


def _recon_dict(recon: Any) -> dict[str, Any]:
    """Best-effort serialization for ReconciliationReport."""
    if hasattr(recon, "model_dump"):
        return recon.model_dump()
    data: dict[str, Any] = {}
    for key in (
        "source_total",
        "would_import",
        "imported",
        "skipped_existing",
        "skipped_invalid",
        "failed",
        "complete",
        "by_entity",
        "outcomes",
    ):
        if hasattr(recon, key):
            value = getattr(recon, key)
            if key == "outcomes" and value is not None:
                data[key] = [
                    o.to_dict() if hasattr(o, "to_dict") else asdict(o)
                    if hasattr(o, "__dataclass_fields__")
                    else dict(o)
                    for o in value
                ]
            else:
                data[key] = value
    # Prefer markdown summary when available.
    if hasattr(recon, "to_markdown"):
        data["markdown"] = recon.to_markdown()
    return data


def export_df_feed(home: Path | str, *, limit: int = 500) -> dict[str, Any]:
    """Build a Roamboard-shaped feed envelope from DF travel objects (push preview).

    Does not POST anywhere — cutover push remains manual.
    """
    from domain_foundry_core.security.store import connect_ro

    api = _ready_api(Path(home).expanduser())
    domains_db = api.workspace.domains_db
    trip_payloads: list[dict[str, Any]] = []
    if domains_db.exists():
        conn = connect_ro(domains_db)
        try:
            trips = conn.execute(
                "SELECT * FROM travel__trip WHERE COALESCE(tombstoned, 0) = 0 "
                "ORDER BY start_date, object_uid LIMIT ?",
                (limit,),
            ).fetchall()
            items = conn.execute(
                "SELECT * FROM travel__timeline_item WHERE COALESCE(tombstoned, 0) = 0 "
                "ORDER BY scheduled_at, object_uid LIMIT ?",
                (limit * 10,),
            ).fetchall()
            items_by_trip: dict[str, list[dict[str, Any]]] = {}
            for item in items:
                trip_key = str(item["trip"] or item["trip_id"] or "")
                items_by_trip.setdefault(trip_key, []).append(
                    {
                        "id": f"item_{item['object_uid']}",
                        "title": item["title"],
                        "itemType": item["item_type"],
                        "category": item["item_type_canonical"] or item["item_type"],
                        "startDateTime": item["start_datetime"],
                        "endDateTime": item["end_datetime"],
                        "locationName": item["location_name"] or item["location"],
                        "lat": item["lat"],
                        "lng": item["lng"],
                        "status": item["status"],
                        "notes": item["notes"],
                        "source": "domain_foundry",
                    }
                )
            for trip in trips:
                slug = trip["slug"] or ""
                trip_payloads.append(
                    {
                        "id": f"trip_{slug}",
                        "slug": slug,
                        "name": trip["name"],
                        "startDate": trip["start_date"],
                        "endDate": trip["end_date"],
                        "primaryDestination": trip["primary_destination"]
                        or trip["destination"],
                        "status": trip["status"],
                        "days": [],
                        "backlogItems": items_by_trip.get(str(slug), [])
                        + items_by_trip.get(str(trip["trip_id"] or ""), []),
                        "tasks": [],
                        "openQuestions": [],
                        "readiness": {
                            "score": trip["readiness_score"],
                            "criticalGaps": [],
                            "warnings": [],
                        },
                    }
                )
        except Exception:
            trip_payloads = []
        finally:
            conn.close()

    stable = {"schemaVersion": 2, "trips": trip_payloads}
    checksum = __import__("hashlib").sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    from datetime import datetime, timezone

    return {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "checksum": checksum,
        "trips": trip_payloads,
        "source": "domain_foundry",
        "notes": [
            "Push preview only — not posted to Roamboard. Cutover remains manual.",
        ],
    }
