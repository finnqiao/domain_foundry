"""Block-data adapter — direct compiled queries against domains.sqlite (RO).

Blocks never see raw SQL. Each pack view in `projections.yaml` binds a block
(timeline / list / stats / search / detail) to schema fields; this module
compiles that binding into a safe, parameterized read-only query. Direct-query
first (§P4): no cache until profiling demands one.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from domain_foundry_core.packs.models import DomainPack
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.packs.schema_compiler import table_name
from domain_foundry_core.paths import Workspace
from domain_foundry_core.projections.capabilities import (
    annotate_derived,
    capability_for_gallery,
    comparison_spec,
    derived_metric_specs,
    metric_value,
    parse_attachment_value,
)
from domain_foundry_core.security.store import connect_ro

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_BASE_COLUMNS = ("object_uid", "entry_id", "created_at", "updated_at")


class BlockDataError(ValueError):
    pass


def _safe_field(obj_fields: dict[str, Any], name: str | None) -> str | None:
    if not name:
        return None
    if name in _BASE_COLUMNS:
        return name
    if name in obj_fields and _IDENT_RE.match(name):
        return name
    raise BlockDataError(f"unknown or unsafe field: {name!r}")


class BlockDataService:
    """Compiles pack view bindings into RO parameterized queries."""

    def __init__(
        self, workspace: Workspace, *, registry: PackRegistry | None = None
    ) -> None:
        self.ws = workspace
        self.registry = registry or PackRegistry(workspace)

    def views(self, domain: str) -> list[dict[str, Any]]:
        pack = self.registry.get(domain)
        if pack is None:
            return []
        return _views_of(pack)

    def view_data(self, domain: str, view_id: str, *, limit: int = 100) -> dict[str, Any]:
        pack = self.registry.get(domain)
        if pack is None:
            raise BlockDataError(f"no pack for domain {domain!r}")
        view = next((v for v in _views_of(pack) if v.get("id") == view_id), None)
        if view is None:
            raise BlockDataError(f"unknown view {view_id!r} in {domain!r}")
        return self._compile_view(pack, view, limit=limit)

    def refresh(self, domain: str, object_type: str, *, limit: int = 100) -> dict[str, Any]:
        """Compute data for every view bound to `object_type` (drain convergence)."""
        pack = self.registry.get(domain)
        if pack is None:
            return {"views": 0}
        computed = 0
        for view in _views_of(pack):
            if view.get("object") == object_type or object_type in (
                view.get("objects") or []
            ):
                self._compile_view(pack, view, limit=limit)
                computed += 1
        return {"views": computed}

    def _compile_view(
        self, pack: DomainPack, view: dict[str, Any], *, limit: int
    ) -> dict[str, Any]:
        block = str(view.get("block") or "list")
        object_type = view.get("object") or (view.get("objects") or [None])[0]
        if not object_type or object_type not in pack.objects:
            raise BlockDataError(f"view {view.get('id')!r} has no valid object")
        obj = pack.objects[object_type]
        obj_fields = {k: v for k, v in obj.fields.items()}
        config = view.get("config") or {}
        tname = table_name(pack.name, object_type)

        if block == "timeline":
            result = self._timeline(pack, object_type, tname, obj_fields, config, limit)
        elif block == "stats":
            result = self._stats(pack, object_type, tname, obj_fields, config, limit)
        elif block == "history":
            result = self._history(tname, obj_fields, config, limit)
        elif block == "planner":
            result = self._planner(tname, obj_fields, config, limit)
        elif block == "map":
            result = self._map(pack, view, config, limit)
        elif block == "gallery":
            result = self._gallery(pack, object_type, tname, obj_fields, config, limit)
        elif block == "compare":
            result = self._compare(pack, object_type, tname, obj_fields, config, limit)
        else:  # list / search / unknown → plain listing
            result = self._list(pack, object_type, tname, obj_fields, config, limit)
        # Every view carries its object type so the app can open the detail
        # view (/api/objects/<domain>/<object_type>/<uid>) for any row.
        result.setdefault("object_type", object_type)
        result.setdefault("domain", pack.name)
        result.setdefault("view_id", view.get("id"))
        return result

    def _rows(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        if not self.ws.domains_db.exists():
            return []
        conn = connect_ro(self.ws.domains_db)
        try:
            cur = conn.execute(sql, params)
            return [{k: r[k] for k in r.keys()} for r in cur.fetchall()]
        finally:
            conn.close()

    # ---------------------------------------------------------------- ask (S1.4)
    def object_rows(
        self,
        domain: str,
        object_type: str,
        *,
        limit: int = 20,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """Newest-first live canonical rows for one schema object type."""
        pack = self.registry.get(domain)
        if pack is None or object_type not in pack.objects:
            raise BlockDataError(f"unknown {domain}.{object_type}")
        tname = table_name(domain, object_type)
        sql = f"SELECT * FROM {tname} WHERE tombstoned = 0"
        params: list[Any] = []
        if since:
            sql += " AND created_at >= ?"
            params.append(since)
        if until:
            sql += " AND created_at < ?"
            params.append(until)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        return self._rows(sql, params)

    def aggregate_field(
        self,
        domain: str,
        object_type: str,
        *,
        op: str,
        field: str | None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate a schema-validated field using a read-only query."""
        pack = self.registry.get(domain)
        if pack is None or object_type not in pack.objects:
            raise BlockDataError(f"unknown {domain}.{object_type}")
        obj_fields = dict(pack.objects[object_type].fields)
        if op not in {"count", "sum", "avg", "min", "max"}:
            raise BlockDataError(f"unknown aggregate op {op!r}")
        tname = table_name(domain, object_type)
        column = _safe_field(obj_fields, field) if op != "count" else None
        expression = "COUNT(*)" if op == "count" else f"{op.upper()}({column})"
        sql = f"SELECT {expression} AS v FROM {tname} WHERE tombstoned = 0"
        params: list[Any] = []
        if since:
            sql += " AND created_at >= ?"
            params.append(since)
        if until:
            sql += " AND created_at < ?"
            params.append(until)
        rows = self._rows(sql, params)
        return {"op": op, "field": field, "value": rows[0]["v"] if rows else None}

    def export_rows(self, domain: str, object_type: str) -> list[dict[str, Any]]:
        """Return every live canonical row for export, oldest first."""
        pack = self.registry.get(domain)
        if pack is None or object_type not in pack.objects:
            raise BlockDataError(f"unknown {domain}.{object_type}")
        tname = table_name(domain, object_type)
        return self._rows(
            f"SELECT * FROM {tname} WHERE tombstoned = 0 ORDER BY created_at ASC",
            [],
        )

    def _list(
        self,
        pack: DomainPack,
        object_type: str,
        tname: str,
        obj_fields: dict,
        config: dict,
        limit: int,
    ) -> dict[str, Any]:
        group_by = _safe_field(obj_fields, config.get("group_by"))
        order = "created_at DESC"
        sql = (
            f"SELECT * FROM {tname} WHERE tombstoned = 0 ORDER BY {order} LIMIT ?"
        )
        rows = self._rows(sql, [int(limit)])
        rows = _with_derived(pack, object_type, rows, config)
        out: dict[str, Any] = {"block": "list", "rows": rows, "count": len(rows)}
        if group_by:
            groups: dict[str, list[dict[str, Any]]] = {}
            for r in rows:
                key = str(r.get(group_by) if r.get(group_by) is not None else "—")
                groups.setdefault(key, []).append(r)
            out["group_by"] = group_by
            out["groups"] = groups
        return out

    def _timeline(
        self,
        pack: DomainPack,
        object_type: str,
        tname: str,
        obj_fields: dict,
        config: dict,
        limit: int,
    ) -> dict[str, Any]:
        date_field = _safe_field(obj_fields, config.get("date_field")) or "created_at"
        media_field = _safe_field(obj_fields, config.get("media_field"))
        sql = (
            f"SELECT * FROM {tname} WHERE tombstoned = 0 "
            f"ORDER BY {date_field} DESC LIMIT ?"
        )
        rows = self._rows(sql, [int(limit)])
        rows = _with_derived(pack, object_type, rows, config)
        return {
            "block": "timeline",
            "date_field": date_field,
            "media_field": media_field,
            "rows": rows,
            "count": len(rows),
        }

    def _stats(
        self,
        pack: DomainPack,
        object_type: str,
        tname: str,
        obj_fields: dict,
        config: dict,
        limit: int,
    ) -> dict[str, Any]:
        measures = config.get("measures") or []
        rows = self._rows(
            f"SELECT * FROM {tname} WHERE tombstoned = 0 ORDER BY created_at ASC LIMIT ?",
            [int(limit)],
        )
        rows = _with_derived(pack, object_type, rows, config)
        derived_ids = {spec["id"] for spec in derived_metric_specs(pack, object_type)}
        results: list[dict[str, Any]] = []
        for measure in measures:
            requested_field = str(measure.get("field") or "")
            field = None if requested_field in derived_ids else _safe_field(obj_fields, requested_field)
            agg = str(measure.get("agg") or "count")
            if field is None and requested_field not in derived_ids:
                continue
            values = [
                metric_value(r, requested_field)
                for r in rows
                if metric_value(r, requested_field) is not None
            ]
            if agg == "distribution":
                dist = Counter(str(v) for v in values)
                results.append({"field": requested_field, "agg": agg, "distribution": dict(dist)})
            elif agg == "trend":
                trend = [
                    {"at": r.get("created_at"), "value": metric_value(r, requested_field)}
                    for r in rows
                    if metric_value(r, requested_field) is not None
                ]
                results.append({"field": requested_field, "agg": agg, "trend": trend})
            else:  # count / default
                results.append({"field": requested_field, "agg": "count", "count": len(values)})
        return {
            "block": "stats",
            "measures": results,
            "total": len(rows),
            "derived_metrics": derived_metric_specs(pack, object_type),
        }

    def _gallery(
        self,
        pack: DomainPack,
        object_type: str,
        tname: str,
        obj_fields: dict,
        config: dict,
        limit: int,
    ) -> dict[str, Any]:
        gallery_id = str(config.get("gallery") or config.get("id") or "")
        gallery = capability_for_gallery(pack, object_type, gallery_id)
        if gallery is None:
            raise BlockDataError(f"gallery {gallery_id!r} is not declared for {object_type}")
        field = _safe_field(obj_fields, gallery.get("field"))
        rows = self._rows(
            f"SELECT * FROM {tname} WHERE tombstoned = 0 ORDER BY created_at DESC LIMIT ?",
            [int(limit)],
        )
        capture_attachments = self._capture_attachments([str(row.get("entry_id")) for row in rows])
        items: list[dict[str, Any]] = []
        for row in rows:
            attachments = parse_attachment_value(row.get(field)) if field else []
            if gallery.get("source") == "capture_attachments":
                attachments.extend(capture_attachments.get(str(row.get("entry_id")), []))
            for attachment in attachments:
                item = dict(attachment)
                digest = item.get("sha256")
                if digest:
                    content_type = str(item.get("content_type") or "")
                    query = f"?content_type={content_type}" if content_type else ""
                    item["url"] = f"/api/attachments/{digest}{query}"
                items.append(
                    {
                        "object_uid": row.get("object_uid"),
                        "entry_id": row.get("entry_id"),
                        "title": row.get(pack.objects[object_type].title_field or "object_uid"),
                        "attachment": item,
                    }
                )
        return {
            "block": "gallery",
            "gallery": gallery,
            "items": items,
            "count": len(items),
        }

    def _compare(
        self,
        pack: DomainPack,
        object_type: str,
        tname: str,
        obj_fields: dict,
        config: dict,
        limit: int,
    ) -> dict[str, Any]:
        comparison = comparison_spec(pack, object_type, config.get("comparison"))
        if comparison is None:
            raise BlockDataError(f"comparison is not declared for {object_type}")
        rows = self._rows(
            f"SELECT * FROM {tname} WHERE tombstoned = 0 ORDER BY created_at ASC LIMIT ?",
            [int(limit)],
        )
        rows = annotate_derived(pack, object_type, rows)
        rows.reverse()
        metrics = [
            spec
            for spec in derived_metric_specs(pack, object_type)
            if spec.get("id") in set(comparison.get("metrics") or [])
        ]
        return {
            "block": "compare",
            "comparison": comparison,
            "rows": rows,
            "metrics": metrics,
            "selection_limit": int(comparison.get("selection_limit") or 3),
            "count": len(rows),
        }

    def _capture_attachments(self, entry_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        ids = [entry_id for entry_id in entry_ids if entry_id and entry_id != "None"]
        if not ids or not self.ws.ledger_db.exists():
            return {}
        placeholders = ",".join("?" for _ in ids)
        conn = connect_ro(self.ws.ledger_db)
        try:
            rows = conn.execute(
                f"""
                SELECT e.id AS entry_id, c.attachments_json
                FROM entry e JOIN capture_event c ON c.id = e.capture_event_id
                WHERE e.id IN ({placeholders})
                """,
                ids,
            ).fetchall()
            out: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                out[str(row["entry_id"])] = parse_attachment_value(row["attachments_json"])
            return out
        finally:
            conn.close()

    def _history(
        self, tname: str, obj_fields: dict, config: dict, limit: int
    ) -> dict[str, Any]:
        """Periodized past view: rows bucketed by week/month of a date field."""
        date_field = _safe_field(obj_fields, config.get("date_field")) or "created_at"
        period = str(config.get("period") or "month")
        if period not in {"day", "week", "month"}:
            period = "month"
        sql = (
            f"SELECT * FROM {tname} WHERE tombstoned = 0 "
            f"ORDER BY {date_field} DESC LIMIT ?"
        )
        rows = self._rows(sql, [int(limit)])
        buckets: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            raw = str(r.get(date_field) or r.get("created_at") or "")
            key = _period_key(raw, period)
            buckets.setdefault(key, []).append(r)
        periods = [
            {"period": k, "count": len(v), "rows": v}
            for k, v in sorted(buckets.items(), reverse=True)
        ]
        return {
            "block": "history",
            "date_field": date_field,
            "granularity": period,
            "periods": periods,
            "count": len(rows),
        }

    def _planner(
        self, tname: str, obj_fields: dict, config: dict, limit: int
    ) -> dict[str, Any]:
        """Future-dated items + a 'plan next' affordance (rendered client-side)."""
        date_field = _safe_field(obj_fields, config.get("date_field")) or "created_at"
        status_field = _safe_field(obj_fields, config.get("status_field"))
        group_by = _safe_field(obj_fields, config.get("group_by"))
        sql = (
            f"SELECT * FROM {tname} WHERE tombstoned = 0 "
            f"ORDER BY {date_field} ASC LIMIT ?"
        )
        rows = self._rows(sql, [int(limit)])
        from domain_foundry_core.clock import now_iso

        today = now_iso()
        upcoming = [r for r in rows if str(r.get(date_field) or "") >= today]
        past = [r for r in rows if str(r.get(date_field) or "") < today]

        def grouped(values: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
            if not group_by:
                return {}
            groups: dict[str, list[dict[str, Any]]] = {}
            for row in values:
                key = str(row.get(group_by) if row.get(group_by) is not None else "—")
                groups.setdefault(key, []).append(row)
            return groups

        return {
            "block": "planner",
            "date_field": date_field,
            "status_field": status_field,
            "group_by": group_by,
            "object": tname,
            "upcoming": upcoming,
            "past": past,
            "groups": grouped(upcoming),
            "past_groups": grouped(past),
            "statuses": list(config.get("statuses") or []),
            "count": len(rows),
        }

    def _map(
        self,
        pack: DomainPack,
        view: dict[str, Any],
        config: dict,
        limit: int,
    ) -> dict[str, Any]:
        """Been-to map: rows with lat/lng across one or more venue object types.

        Null geo degrades cleanly — ungeocoded venues are counted but omitted
        from ``rows`` / ``features`` so the SPA can still render.
        """
        object_types = list(view.get("objects") or [])
        single = view.get("object")
        if single and single not in object_types:
            object_types.insert(0, str(single))
        object_types = [ot for ot in object_types if ot in pack.objects]
        if not object_types:
            raise BlockDataError(f"view {view.get('id')!r} has no valid object")

        type_filter = config.get("types") or config.get("filter_types")
        if type_filter:
            wanted = {str(t) for t in type_filter}
            object_types = [ot for ot in object_types if ot in wanted]

        per_type = max(1, int(limit))
        rows: list[dict[str, Any]] = []
        skipped_null_geo = 0
        scanned = 0
        for object_type in object_types:
            obj = pack.objects[object_type]
            obj_fields = {k: v for k, v in obj.fields.items()}
            if "lat" not in obj_fields or "lng" not in obj_fields:
                continue
            tname = table_name(pack.name, object_type)
            title_field = obj.title_field
            sql = (
                f"SELECT * FROM {tname} WHERE tombstoned = 0 "
                f"ORDER BY created_at DESC LIMIT ?"
            )
            for row in self._rows(sql, [per_type]):
                scanned += 1
                row = dict(row)
                row["object_type"] = object_type
                if title_field and row.get(title_field) is not None:
                    row["_title"] = row.get(title_field)
                lat, lng = row.get("lat"), row.get("lng")
                if lat is None or lng is None:
                    skipped_null_geo += 1
                    continue
                try:
                    lat_f = float(lat)
                    lng_f = float(lng)
                except (TypeError, ValueError):
                    skipped_null_geo += 1
                    continue
                row["lat"] = lat_f
                row["lng"] = lng_f
                rows.append(row)

        features = [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(r["lng"]), float(r["lat"])],
                },
                "properties": {
                    "object_uid": r.get("object_uid"),
                    "object_type": r.get("object_type"),
                    "entry_id": r.get("entry_id"),
                    "title": r.get("_title") or r.get("place_name") or r.get("object_uid"),
                    "place_name": r.get("place_name"),
                },
            }
            for r in rows
        ]
        return {
            "block": "map",
            "rows": rows,
            "features": features,
            "count": len(rows),
            "scanned": scanned,
            "skipped_null_geo": skipped_null_geo,
            "object_types": object_types,
            "geojson": {"type": "FeatureCollection", "features": features},
        }


class BlockDataAdapter:
    """Projection adapter for the app feed: direct queries, watermark on success."""

    name = "app_feed"

    def __init__(
        self, workspace: Workspace, *, registry: PackRegistry | None = None
    ) -> None:
        self.ws = workspace
        self.registry = registry or PackRegistry(workspace)
        self.service = BlockDataService(workspace, registry=self.registry)

    def render(self, object_key: str, outbox_row: dict[str, Any]) -> dict[str, Any]:
        domain, _, object_type = object_key.partition(":")
        if not domain or not object_type:
            return {"status": "skipped", "reason": f"bad object_key {object_key!r}"}
        try:
            summary = self.service.refresh(domain, object_type)
        except BlockDataError as exc:
            return {"status": "skipped", "reason": str(exc)}
        return {"status": "refreshed", **summary}


def _period_key(iso_ts: str, period: str) -> str:
    """Bucket an ISO timestamp into a day/week/month key (string sort-safe)."""
    date_part = (iso_ts or "")[:10]
    if len(date_part) < 10:
        return date_part or "unknown"
    if period == "day":
        return date_part
    if period == "month":
        return date_part[:7]
    # week: ISO year-week
    try:
        from datetime import date

        y, m, d = (int(x) for x in date_part.split("-"))
        iso = date(y, m, d).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except (ValueError, TypeError):
        return date_part


def _views_of(pack: DomainPack) -> list[dict[str, Any]]:
    views = pack.projections.app.get("views") if pack.projections.app else None
    if not views:
        return []
    normalized: list[dict[str, Any]] = []
    for v in views:
        if isinstance(v, dict):
            normalized.append(v)
        else:  # pydantic AppView or similar
            normalized.append(json.loads(json.dumps(v, default=lambda o: o.__dict__)))
    return normalized


def _with_derived(
    pack: DomainPack,
    object_type: str,
    rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    requested = config.get("derived_metrics") or config.get("derived")
    if requested is None:
        return rows
    if requested is True:
        return annotate_derived(pack, object_type, rows)
    wanted = {str(item) for item in requested} if isinstance(requested, list) else set()
    annotated = annotate_derived(pack, object_type, rows)
    if not wanted:
        return annotated
    return [
        {
            **row,
            "derived": {
                key: value for key, value in (row.get("derived") or {}).items() if key in wanted
            },
        }
        for row in annotated
    ]
