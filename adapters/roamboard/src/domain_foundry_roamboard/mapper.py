"""Map Roamboard shapes → DomainFoundry travel importer records."""

from __future__ import annotations

from typing import Any

from domain_foundry_roamboard.shapes import (
    feed_trips,
    item_source_key,
    iter_timeline_items,
    patch_source_key,
    patch_updates,
    trip_source_key,
)

CHANNEL = "roamboard"


def source_ref_trip(key: str) -> str:
    return f"roamboard:trip:{key}"


def source_ref_item(key: str) -> str:
    return f"roamboard:timeline_item:{key}"


def source_ref_event(key: str) -> str:
    return f"roamboard:event:{key}"


def source_ref_patch(key: str) -> str:
    return f"roamboard:patch:{key}"


def mapping_config_dict() -> dict[str, Any]:
    """Importer mapping for Roamboard → travel (used by GenericImporter)."""
    return {
        "name": "roamboard-sync",
        "channel": CHANNEL,
        "notes": "Roamboard feed/patch import into DomainFoundry travel (Phase 7).",
        "entities": [
            {
                "name": "trip",
                "domain": "travel",
                "object_type": "trip",
                "source_ref_template": "roamboard:trip:{id}",
                "id_field": "id",
                "timestamp_field": "created_at",
                "updated_at_field": "updated_at",
                "raw_text_template": "{name} ({primary_destination}) — {status}",
                "required_source_fields": ["name"],
                "field_map": {
                    "name": "name",
                    "slug": "slug",
                    "destination": "destination",
                    "primary_destination": "primary_destination",
                    "start_date": "start_date",
                    "end_date": "end_date",
                    "status": "status",
                    "readiness_score": "readiness_score",
                    "cover_image_path": "cover_image_path",
                    "notes_path": "notes_path",
                    "notes": "notes",
                },
            },
            {
                "name": "timeline_item",
                "domain": "travel",
                "object_type": "timeline_item",
                "source_ref_template": "roamboard:timeline_item:{id}",
                "id_field": "id",
                "timestamp_field": "created_at",
                "updated_at_field": "updated_at",
                "raw_text_template": "{title} ({item_type}) — {location_name}",
                "required_source_fields": ["title"],
                "field_map": {
                    "title": "title",
                    "trip": "trip",
                    "trip_id": "trip_id",
                    "day_id": "day_id",
                    "item_type": "item_type",
                    "item_type_canonical": "item_type_canonical",
                    "day": "day",
                    "start_datetime": "start_datetime",
                    "end_datetime": "end_datetime",
                    "timezone": "timezone",
                    "location": "location",
                    "location_name": "location_name",
                    "lat": "lat",
                    "lng": "lng",
                    "status": "status",
                    "confidence": "confidence",
                    "source": "source",
                    "sort_order": "sort_order",
                    "is_all_day": "is_all_day",
                    "is_overnight": "is_overnight",
                    "is_flexible": "is_flexible",
                    "guest_count": "guest_count",
                    "reservation_channel": "reservation_channel",
                    "package_label": "package_label",
                    "scheduled_at": "scheduled_at",
                    "notes": "notes",
                },
            },
            {
                "name": "event_log",
                "domain": "travel",
                "object_type": "event_log",
                "source_ref_template": "roamboard:event:{id}",
                "id_field": "id",
                "timestamp_field": "created_at",
                "updated_at_field": None,
                "raw_text_template": "{event_type} trip={trip_id}",
                "required_source_fields": ["event_type"],
                "actor_field": "created_by",
                "default_actor": "roamboard",
                "field_map": {
                    "event_type": "event_type",
                    "trip_id": "trip_id",
                    "timeline_item_id": "timeline_item_id",
                    "event_json": "event_json",
                    "created_by": "created_by",
                    "noted_at": "created_at",
                },
            },
        ],
    }


def feed_to_records(feed: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Flatten a Roamboard feed into importer entity records."""
    trips_out: list[dict[str, Any]] = []
    items_out: list[dict[str, Any]] = []
    events_out: list[dict[str, Any]] = []

    for trip in feed_trips(feed):
        key = trip_source_key(trip)
        updated = trip.get("updatedAt") or trip.get("updated_at")
        created = updated or trip.get("createdAt") or trip.get("created_at")
        readiness = (trip.get("readiness") or {}).get("score")
        if readiness is None:
            readiness = trip.get("readiness_score")
        primary = trip.get("primaryDestination") or trip.get("primary_destination")
        trips_out.append(
            {
                "id": key,
                "name": trip.get("name") or "",
                "slug": trip.get("slug") or key,
                "destination": primary,
                "primary_destination": primary,
                "start_date": trip.get("startDate") or trip.get("start_date"),
                "end_date": trip.get("endDate") or trip.get("end_date"),
                "status": trip.get("status") or "planning",
                "readiness_score": readiness,
                "cover_image_path": trip.get("coverImageUrl") or trip.get("cover_image_path"),
                "notes_path": trip.get("notesPath") or trip.get("notes_path"),
                "notes": trip.get("notes"),
                "created_at": created or "1970-01-01T00:00:00+00:00",
                "updated_at": updated or created or "1970-01-01T00:00:00+00:00",
            }
        )

        trip_numeric = trip.get("sourceId") if trip.get("sourceId") is not None else trip.get("source_id")
        for item in iter_timeline_items(trip):
            item_key = item_source_key(item)
            location = item.get("locationName") or item.get("location_name") or item.get("location")
            start_dt = item.get("startDateTime") or item.get("start_datetime")
            end_dt = item.get("endDateTime") or item.get("end_datetime")
            day = item.get("day") or item.get("localDate") or item.get("local_date")
            if not day and start_dt:
                day = str(start_dt).split("T", 1)[0]
            geo = item.get("geo") or {}
            lat = item.get("lat") if item.get("lat") is not None else geo.get("lat")
            lng = item.get("lng") if item.get("lng") is not None else geo.get("lng")
            scheduled = start_dt or (
                f"{day}T12:00:00+00:00" if day else "1970-01-01T00:00:00+00:00"
            )
            item_type = item.get("itemType") or item.get("item_type") or item.get("category") or "activity"
            items_out.append(
                {
                    "id": item_key,
                    "title": item.get("title") or "",
                    "trip": key,
                    "trip_id": trip_numeric,
                    "day_id": _day_source_id(item),
                    "item_type": item_type,
                    "item_type_canonical": item.get("category") or item_type,
                    "day": day,
                    "start_datetime": start_dt,
                    "end_datetime": end_dt,
                    "timezone": item.get("timezone"),
                    "location": location,
                    "location_name": location,
                    "lat": lat,
                    "lng": lng,
                    "status": item.get("status") or "planned",
                    "confidence": item.get("confidence"),
                    "source": item.get("source") or "roamboard",
                    "sort_order": item.get("sortOrder") or item.get("sort_order"),
                    "is_all_day": bool(item.get("isAllDay") or item.get("is_all_day") or False),
                    "is_overnight": bool(item.get("isOvernight") or item.get("is_overnight") or False),
                    "is_flexible": bool(item.get("isFlexible") or item.get("is_flexible") or False),
                    "guest_count": item.get("guestCount") or item.get("guest_count"),
                    "reservation_channel": item.get("reservationChannel")
                    or item.get("reservation_channel"),
                    "package_label": item.get("packageLabel") or item.get("package_label"),
                    "scheduled_at": scheduled,
                    "notes": item.get("notes"),
                    "created_at": scheduled,
                    "updated_at": scheduled,
                }
            )

        # Synthetic sync event per trip for audit parity (idempotent on trip key).
        events_out.append(
            {
                "id": f"feed:{key}",
                "event_type": "roamboard_feed_import",
                "trip_id": trip_numeric,
                "timeline_item_id": None,
                "event_json": f'{{"slug": "{key}", "source": "roamboard_feed"}}',
                "created_by": "roamboard",
                "created_at": updated or created or "1970-01-01T00:00:00+00:00",
            }
        )

    return {"trip": trips_out, "timeline_item": items_out, "event_log": events_out}


def patch_bundle_to_records(bundle: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Convert a pending-patch bundle into event_log rows (+ optional trip stub).

    Full chat/LLM interpretation stays on the private Hermes path until cutover.
    Here we record each update as an ``event_log`` with ``roamboard:patch:…``
    provenance so DF can shadow-diff without mutating travel.sqlite.
    """
    session_id = (
        bundle.get("clientSessionId")
        or bundle.get("client_session_id")
        or "bundle"
    )
    trip_slug = bundle.get("tripSlug") or bundle.get("trip_slug") or "unknown"
    events: list[dict[str, Any]] = []
    trips: list[dict[str, Any]] = []
    if trip_slug and trip_slug != "unknown":
        trips.append(
            {
                "id": trip_slug,
                "name": trip_slug.replace("-", " ").title(),
                "slug": trip_slug,
                "destination": None,
                "primary_destination": None,
                "start_date": None,
                "end_date": None,
                "status": "planning",
                "readiness_score": None,
                "created_at": "1970-01-01T00:00:00+00:00",
                "updated_at": "1970-01-01T00:00:00+00:00",
            }
        )

    for update in patch_updates(bundle):
        key = patch_source_key(update, session_id=str(session_id))
        update_type = update.get("type") or "unknown"
        payload = update.get("payload") or {}
        events.append(
            {
                "id": key,
                "event_type": f"roamboard_patch:{update_type}",
                "trip_id": None,
                "timeline_item_id": None,
                "event_json": _safe_json(
                    {
                        "session_id": session_id,
                        "trip_slug": trip_slug,
                        "type": update_type,
                        "payload": payload,
                        "reason": update.get("reason_text")
                        or update.get("reasonText"),
                    }
                ),
                "created_by": "roamboard",
                "created_at": "1970-01-01T00:00:00+00:00",
            }
        )

    return {"trip": trips, "timeline_item": [], "event_log": events}


def _day_source_id(item: dict[str, Any]) -> int | None:
    day_id = item.get("dayId") or item.get("day_id")
    if day_id is None:
        return None
    text = str(day_id).removeprefix("day_")
    if text.isdigit():
        return int(text)
    return None


def _safe_json(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, default=str)
