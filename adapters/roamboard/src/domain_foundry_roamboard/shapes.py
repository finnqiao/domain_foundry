"""Normalize Roamboard feed / patch bundle shapes into flat entity records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_feed(path: Path | str) -> dict[str, Any]:
    """Load a Roamboard feed envelope (schemaVersion 2) from disk."""
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Roamboard feed must be a JSON object")
    return payload


def load_patch_bundle(path: Path | str) -> dict[str, Any]:
    """Load a pending-patch bundle (drain_roamboard_updates shape)."""
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Roamboard patch bundle must be a JSON object")
    return payload


def feed_trips(feed: dict[str, Any]) -> list[dict[str, Any]]:
    trips = feed.get("trips") or []
    if not isinstance(trips, list):
        raise ValueError("feed.trips must be a list")
    return [dict(t) for t in trips if isinstance(t, dict)]


def iter_timeline_items(trip: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten day-scoped + backlog timeline items for one trip."""
    items: list[dict[str, Any]] = []
    for day in trip.get("days") or []:
        if not isinstance(day, dict):
            continue
        local_date = day.get("localDate") or day.get("local_date")
        for item in day.get("timelineItems") or day.get("timeline_items") or []:
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            if local_date and not enriched.get("day") and not enriched.get("localDate"):
                enriched["day"] = local_date
            items.append(enriched)
    for item in trip.get("backlogItems") or trip.get("backlog_items") or []:
        if isinstance(item, dict):
            items.append(dict(item))
    return items


def trip_source_key(trip: dict[str, Any]) -> str:
    """Stable trip identity for ``roamboard:trip:…`` source_refs."""
    slug = (trip.get("slug") or "").strip()
    if slug:
        return slug
    source_id = trip.get("sourceId") if trip.get("sourceId") is not None else trip.get("source_id")
    if source_id is not None:
        return str(source_id)
    trip_id = trip.get("id")
    if trip_id is not None:
        return str(trip_id).removeprefix("trip_")
    raise ValueError("trip missing slug/sourceId/id")


def item_source_key(item: dict[str, Any]) -> str:
    """Stable timeline item identity for ``roamboard:timeline_item:…``."""
    source_id = item.get("sourceId") if item.get("sourceId") is not None else item.get("source_id")
    if source_id is not None:
        return str(source_id)
    item_id = item.get("id")
    if item_id is None:
        raise ValueError("timeline item missing sourceId/id")
    return str(item_id).removeprefix("item_")


def patch_updates(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    updates = bundle.get("updates") or []
    if not isinstance(updates, list):
        return []
    return [dict(u) for u in updates if isinstance(u, dict)]


def patch_source_key(update: dict[str, Any], *, session_id: str | None = None) -> str:
    update_id = (
        update.get("updateId")
        or update.get("update_id")
        or update.get("id")
    )
    if update_id:
        return str(update_id)
    # Fall back to a deterministic hash of type+target for fixture stability.
    kind = update.get("type") or "unknown"
    target = update.get("target") or {}
    activity = (
        target.get("activityId")
        or target.get("activity_id")
        or (update.get("payload") or {}).get("sourceId")
        or "na"
    )
    base = f"{kind}:{activity}"
    if session_id:
        return f"{session_id}:{base}"
    return base
