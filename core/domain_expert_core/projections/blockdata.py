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

from domain_expert_core.packs.models import DomainPack
from domain_expert_core.packs.registry import PackRegistry
from domain_expert_core.packs.schema_compiler import table_name
from domain_expert_core.paths import Workspace
from domain_expert_core.security.store import connect_ro

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
            return self._timeline(tname, obj_fields, config, limit)
        if block == "stats":
            return self._stats(tname, obj_fields, config, limit)
        if block in {"list", "search"}:
            return self._list(tname, obj_fields, config, limit)
        # Unknown block: fall back to a plain listing.
        return self._list(tname, obj_fields, config, limit)

    def _rows(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        if not self.ws.domains_db.exists():
            return []
        conn = connect_ro(self.ws.domains_db)
        try:
            cur = conn.execute(sql, params)
            return [{k: r[k] for k in r.keys()} for r in cur.fetchall()]
        finally:
            conn.close()

    def _list(
        self, tname: str, obj_fields: dict, config: dict, limit: int
    ) -> dict[str, Any]:
        group_by = _safe_field(obj_fields, config.get("group_by"))
        order = "created_at DESC"
        sql = (
            f"SELECT * FROM {tname} WHERE tombstoned = 0 ORDER BY {order} LIMIT ?"
        )
        rows = self._rows(sql, [int(limit)])
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
        self, tname: str, obj_fields: dict, config: dict, limit: int
    ) -> dict[str, Any]:
        date_field = _safe_field(obj_fields, config.get("date_field")) or "created_at"
        media_field = _safe_field(obj_fields, config.get("media_field"))
        sql = (
            f"SELECT * FROM {tname} WHERE tombstoned = 0 "
            f"ORDER BY {date_field} DESC LIMIT ?"
        )
        rows = self._rows(sql, [int(limit)])
        return {
            "block": "timeline",
            "date_field": date_field,
            "media_field": media_field,
            "rows": rows,
            "count": len(rows),
        }

    def _stats(
        self, tname: str, obj_fields: dict, config: dict, limit: int
    ) -> dict[str, Any]:
        measures = config.get("measures") or []
        rows = self._rows(
            f"SELECT * FROM {tname} WHERE tombstoned = 0 ORDER BY created_at ASC LIMIT ?",
            [int(limit)],
        )
        results: list[dict[str, Any]] = []
        for measure in measures:
            field = _safe_field(obj_fields, measure.get("field"))
            agg = str(measure.get("agg") or "count")
            if field is None:
                continue
            values = [r.get(field) for r in rows if r.get(field) is not None]
            if agg == "distribution":
                dist = Counter(str(v) for v in values)
                results.append(
                    {"field": field, "agg": agg, "distribution": dict(dist)}
                )
            elif agg == "trend":
                trend = [
                    {"at": r.get("created_at"), "value": r.get(field)}
                    for r in rows
                    if r.get(field) is not None
                ]
                results.append({"field": field, "agg": agg, "trend": trend})
            else:  # count / default
                results.append({"field": field, "agg": "count", "count": len(values)})
        return {"block": "stats", "measures": results, "total": len(rows)}


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
