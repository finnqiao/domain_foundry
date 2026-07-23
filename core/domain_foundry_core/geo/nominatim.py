"""Nominatim geocoder with on-disk JSON cache and polite rate limiting.

Used by Hermes ``tools/geocode_venues.py`` for food/drink venue backfill.
Network calls are injectable so unit tests cover cache hits without HTTP.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from domain_foundry_core.clock import monotonic

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_USER_AGENT = "domain-foundry-geocode/0.1 (personal food map; local tool)"
DEFAULT_MIN_INTERVAL_S = 1.05  # Nominatim usage policy: max 1 req/s


@dataclass(frozen=True)
class GeocodeResult:
    lat: float | None
    lng: float | None
    place_id: str | None
    place_name: str | None
    query: str
    cached: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.lat is not None and self.lng is not None and not self.error

    def to_fields(self) -> dict[str, Any]:
        """Fields suitable for HarnessAPI.correct amend."""
        out: dict[str, Any] = {}
        if self.lat is not None:
            out["lat"] = float(self.lat)
        if self.lng is not None:
            out["lng"] = float(self.lng)
        if self.place_id:
            out["place_id"] = str(self.place_id)
        if self.place_name:
            out["place_name"] = str(self.place_name)
        return out

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GeocodeCache:
    """Directory of one JSON file per query hash."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key_for(query: str) -> str:
        normalized = " ".join(str(query or "").strip().lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]

    def path_for(self, query: str) -> Path:
        return self.root / f"{self.key_for(query)}.json"

    def get(self, query: str) -> GeocodeResult | None:
        path = self.path_for(query)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return GeocodeResult(
            lat=data.get("lat"),
            lng=data.get("lng"),
            place_id=data.get("place_id"),
            place_name=data.get("place_name"),
            query=str(data.get("query") or query),
            cached=True,
            error=data.get("error"),
        )

    def put(self, result: GeocodeResult) -> None:
        path = self.path_for(result.query)
        payload = {
            "query": result.query,
            "lat": result.lat,
            "lng": result.lng,
            "place_id": result.place_id,
            "place_name": result.place_name,
            "error": result.error,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)


FetchFn = Callable[[str, dict[str, str]], list[dict[str, Any]]]


def _default_fetch(url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — Nominatim HTTPS only
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


class NominatimClient:
    """Cached, rate-limited Nominatim search client."""

    def __init__(
        self,
        cache: GeocodeCache,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        fetch: FetchFn | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache = cache
        self.user_agent = user_agent
        self.min_interval_s = max(0.0, float(min_interval_s))
        self._fetch = fetch or _default_fetch
        self._sleep = sleep
        self._last_request_at = 0.0

    def geocode(self, query: str, *, use_cache: bool = True) -> GeocodeResult:
        q = " ".join(str(query or "").strip().split())
        if not q:
            return GeocodeResult(
                lat=None, lng=None, place_id=None, place_name=None, query=q, error="empty_query"
            )
        if use_cache:
            hit = self.cache.get(q)
            if hit is not None:
                return hit

        self._throttle()
        try:
            rows = self._fetch(self._url(q), {"User-Agent": self.user_agent, "Accept": "application/json"})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            # Transient / blocked responses must not poison the cache.
            return GeocodeResult(
                lat=None, lng=None, place_id=None, place_name=None, query=q, error=str(exc)
            )

        if not rows:
            result = GeocodeResult(
                lat=None, lng=None, place_id=None, place_name=None, query=q, error="no_results"
            )
            # Do not cache misses — Nominatim soft-blocks / empty windows should be retryable.
            return result
        else:
            top = rows[0]
            try:
                lat = float(top["lat"])
                lng = float(top["lon"])
            except (KeyError, TypeError, ValueError):
                return GeocodeResult(
                    lat=None,
                    lng=None,
                    place_id=None,
                    place_name=None,
                    query=q,
                    error="bad_response",
                )
            place_id = top.get("place_id")
            result = GeocodeResult(
                lat=lat,
                lng=lng,
                place_id=str(place_id) if place_id is not None else None,
                place_name=str(top.get("display_name") or "") or None,
                query=q,
            )
        if use_cache:
            self.cache.put(result)
        return result

    def _url(self, query: str) -> str:
        params = urllib.parse.urlencode(
            {"q": query, "format": "json", "limit": 1, "addressdetails": 0}
        )
        return f"{NOMINATIM_URL}?{params}"

    def _throttle(self) -> None:
        if self.min_interval_s <= 0:
            self._last_request_at = monotonic()
            return
        now = monotonic()
        wait = self.min_interval_s - (now - self._last_request_at)
        if wait > 0:
            self._sleep(wait)
        self._last_request_at = monotonic()


# Venue object types that carry nullable lat/lng on the food pack.
VENUE_OBJECT_TYPES: tuple[str, ...] = (
    "dining",
    "coffee_note",
    "dining_note",
    "drink_note",
)

_VENUE_NAME_FIELDS: dict[str, tuple[str, ...]] = {
    "dining": ("place_name", "place"),
    "coffee_note": ("place_name", "cafe_name"),
    "dining_note": ("place_name", "restaurant"),
    "drink_note": ("place_name", "producer", "name"),
}

_VENUE_PLACE_FIELDS: dict[str, tuple[str, ...]] = {
    "dining": (),
    "coffee_note": ("city",),
    "dining_note": ("city",),
    "drink_note": ("region",),
}


def _clean_venue_token(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    # OCR / note dumps often append menus after an em/en dash or newline.
    for sep in ("\n", "—", " – ", " - "):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
    # Hard cap keeps Nominatim queries focused.
    if len(text) > 80:
        text = text[:80].rsplit(" ", 1)[0].strip() or text[:80]
    return text


def venue_query(object_type: str, row: dict[str, Any]) -> str | None:
    """Build a Nominatim query from a food venue row, or None if insufficient."""
    name_fields = _VENUE_NAME_FIELDS.get(object_type, ("place_name",))
    place_fields = _VENUE_PLACE_FIELDS.get(object_type, ())
    name = ""
    for field in name_fields:
        cleaned = _clean_venue_token(row.get(field))
        if cleaned:
            name = cleaned
            break
    if not name:
        return None
    parts = [name]
    for field in place_fields:
        cleaned = _clean_venue_token(row.get(field))
        if cleaned:
            parts.append(cleaned)
    return ", ".join(parts)
