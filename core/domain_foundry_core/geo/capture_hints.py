"""Capture-time venue geo hints for food (Phase 6).

Extraction prompts already ask for place_name; this helper:
1. Pulls a coarse place phrase from capture text when missing.
2. Optionally runs Nominatim (lazy) when ``DOMAIN_FOUNDRY_GEOCODE_ON_CAPTURE=1``.

Unresolved venues stay text-only (nullable lat/lng). Confirmation for live
writes still goes through ``HarnessAPI.correct`` / geocode_venues --apply.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from domain_foundry_core.geo.nominatim import (
    GeocodeCache,
    NominatimClient,
    venue_query,
)
from domain_foundry_core.paths import default_home

# "flat white at Onibus Nakameguro" / "dinner at River Station Grill"
_AT_PLACE_RE = re.compile(
    r"(?i)\b(?:at|@)\s+([A-Z][\w''&.\-]*(?:\s+[A-Z][\w''&.\-]*){0,5})"
)
_VENUE_TYPES = frozenset({"dining", "coffee_note", "dining_note", "drink_note"})


def extract_place_hint(raw_text: str) -> str | None:
    """Return a place-name candidate from capture text, or None."""
    text = (raw_text or "").strip()
    if not text:
        return None
    m = _AT_PLACE_RE.search(text)
    if not m:
        return None
    place = m.group(1).strip(" ,.;:")
    # Drop trailing clause words that aren't part of a venue name.
    stop = {"the", "a", "an", "with", "and", "for", "near"}
    parts = [p for p in place.split() if p.lower() not in stop]
    if not parts:
        return None
    return " ".join(parts)


def enrich_venue_fields(
    *,
    object_type: str,
    fields: dict[str, Any],
    raw_text: str,
    geocode: bool | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Return a shallow-copied fields dict with place_name / optional lat/lng.

    Does nothing for non-venue object types. Never overwrites existing geo.
    ``cache_dir`` overrides where geocode responses are cached (defaults to
    ``{workspace}/cache/geocode``); one file per query hash, so repeat lookups
    of the same venue cost nothing.
    """
    if object_type not in _VENUE_TYPES:
        return fields
    out = dict(fields)
    if not out.get("place_name"):
        hint = extract_place_hint(raw_text)
        if hint:
            out["place_name"] = hint

    do_geocode = geocode
    if do_geocode is None:
        do_geocode = os.environ.get("DOMAIN_FOUNDRY_GEOCODE_ON_CAPTURE", "0").lower() in {
            "1",
            "true",
            "on",
            "yes",
        }
    if not do_geocode:
        return out
    if out.get("lat") is not None and out.get("lng") is not None:
        return out

    query = venue_query(object_type, out) or out.get("place_name") or extract_place_hint(
        raw_text
    )
    if not query:
        return out
    try:
        # NominatimClient requires a cache. This used to be `NominatimClient()`,
        # which raised TypeError on every call — and because the whole block is
        # guarded by `except Exception: return out`, enabling
        # DOMAIN_FOUNDRY_GEOCODE_ON_CAPTURE simply never geocoded anything and
        # never said so. Type-checking the call site is what surfaced it.
        root = cache_dir or (default_home() / "cache" / "geocode")
        result = NominatimClient(GeocodeCache(root)).geocode(str(query))
    except Exception:
        return out
    if result.lat is None or result.lng is None:
        return out
    out["lat"] = result.lat
    out["lng"] = result.lng
    if result.place_name and not out.get("place_name"):
        out["place_name"] = result.place_name
    if result.place_id and not out.get("place_id"):
        out["place_id"] = result.place_id
    return out
