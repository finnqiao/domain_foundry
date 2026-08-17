"""Hardening loop (plan §6.2): plain-language schema edits → migration.

An NL edit is parsed into concrete schema changes, previewed as a pack diff,
and — on confirm — applied by: rewriting ``schema.yaml``, bumping the pack
version, writing + executing an ``ALTER TABLE`` migration, refreshing the
schema registry, and appending a routing fixture/eval case for the new shape.
This reuses the §5.7 migration path so hand-edited and generated packs stay
migratable forever.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any

import yaml

from domain_foundry_core.clock import now_iso
from domain_foundry_core.interpret.fewshot import append_eval_case
from domain_foundry_core.packs.loader import load_pack
from domain_foundry_core.packs.models import DomainPack
from domain_foundry_core.packs.schema_compiler import _SQL_TYPE, apply_pack_schema, table_name
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_rw

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_PHOTO_HINT = re.compile(r"(photo|shot|image|picture|pic)", re.IGNORECASE)
_NUM_HINT = re.compile(r"(count|amount|number|qty|quantity|rating|score|weight|hours|minutes|grams|percent|km|miles|pages)", re.IGNORECASE)
_DATE_HINT = re.compile(r"(date|day|_at$|_on$|time)", re.IGNORECASE)


@dataclass
class SchemaChange:
    kind: str  # add_field | rename_field | split_field | add_object | add_capability | identity
    object: str
    field: str = ""
    field_type: str = "text"
    rename_to: str = ""
    into: list[str] = dataclass_field(default_factory=list)
    capability: str = ""

    def describe(self) -> str:
        if self.kind == "add_field":
            return f"add field {self.object}.{self.field} ({self.field_type})"
        if self.kind == "rename_field":
            return f"rename {self.object}.{self.field} → {self.rename_to}"
        if self.kind == "split_field":
            return f"split {self.object}.{self.field} into {', '.join(self.into)}"
        if self.kind == "add_object":
            return f"add object {self.object}"
        if self.kind == "add_capability":
            return f"add capability {self.capability}"
        if self.kind == "identity":
            return f"identity field → {self.field}"
        return self.kind


@dataclass
class HardeningPlan:
    domain: str
    object: str
    changes: list[SchemaChange]
    added_columns: list[tuple[str, str]]  # (name, sql_type)
    renamed_columns: list[tuple[str, str]]  # (old, new)
    migration_sql: str
    summary: list[str]
    ok: bool = True
    error: str | None = None
    added_objects: list[str] = dataclass_field(default_factory=list)
    added_capabilities: list[str] = dataclass_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "object": self.object,
            "summary": self.summary,
            "added": [{"name": n, "sql_type": t} for n, t in self.added_columns],
            "renamed": [{"from": o, "to": n} for o, n in self.renamed_columns],
            "added_objects": list(self.added_objects),
            "added_capabilities": list(self.added_capabilities),
            "migration_sql": self.migration_sql,
            "ok": self.ok,
            "error": self.error,
        }


def looks_like_edit(text: str) -> bool:
    text = text or ""
    return (
        bool(re.search(
            r"\b(add|rename|split|remove|drop|change)\b.*\b(field|column|property|object)\b",
            text, re.IGNORECASE,
        ))
        or bool(re.search(r"\badd a[n]?\b.+\bfield\b", text, re.IGNORECASE))
        or bool(re.search(r"\brename\s+[a-z_][a-z0-9_]*\s+(?:to|into)\s+[a-z_]", text, re.IGNORECASE))
        or bool(re.search(r"\bsplit\s+[a-z_][a-z0-9_]*\s+into\s+[a-z_]", text, re.IGNORECASE))
        or bool(re.search(r"\badd a[n]?\s+[a-z_][a-z0-9_]*\s+object\b", text, re.IGNORECASE))
        or bool(re.search(r"\badd a[n]?\s+(media|map|compare)\s+capability\b", text, re.IGNORECASE))
        or bool(re.search(r"\bidentity should be\b", text, re.IGNORECASE))
    )


def _infer_type(name: str, explicit: str | None) -> str:
    if explicit:
        explicit = explicit.lower()
        alias = {
            "text": "text", "string": "text", "note": "text",
            "number": "number", "numeric": "number", "float": "number",
            "int": "integer", "integer": "integer",
            "bool": "boolean", "boolean": "boolean",
            "date": "date", "datetime": "datetime",
            "enum": "enum", "photo": "attachment", "image": "attachment",
            "attachment": "attachment", "location": "location",
        }
        if explicit in alias:
            return alias[explicit]
    if _PHOTO_HINT.search(name):
        return "attachment"
    if _DATE_HINT.search(name):
        return "date"
    if _NUM_HINT.search(name):
        return "number"
    return "text"


def parse_edit(text: str, pack: DomainPack) -> list[SchemaChange]:
    """Parse a plain-language edit into concrete schema changes."""
    text = (text or "").strip()
    changes: list[SchemaChange] = []
    default_object = _target_object(text, pack)

    for m in re.finditer(
        r"add\s+a[n]?\s+['\"]?(?P<name>[a-z_][a-z0-9_]*)['\"]?\s+object",
        text, re.IGNORECASE,
    ):
        name = m.group("name").lower()
        if name in pack.objects or name in {"field", "column"}:
            continue
        ident = "name" if name.endswith("s") else f"{name}_name"
        if name in {"species", "recipe", "plant", "site"}:
            ident = f"{name}_name"
        changes.append(SchemaChange(kind="add_object", object=name, field=ident))

    for m in re.finditer(
        r"add\s+a[n]?\s+(?P<cap>media|map|compare|gallery)\s+capability",
        text, re.IGNORECASE,
    ):
        cap = m.group("cap").lower()
        if cap == "gallery":
            cap = "media"
        changes.append(SchemaChange(
            kind="add_capability", object=default_object, capability=cap,
        ))

    for m in re.finditer(
        r"identity should be\s+['\"]?(?P<name>[a-z_][a-z0-9_]*)['\"]?",
        text, re.IGNORECASE,
    ):
        new_ident = m.group("name").lower()
        old = pack.objects[default_object].title_field
        if new_ident != old:
            changes.append(SchemaChange(
                kind="identity", object=default_object, field=new_ident, rename_to=new_ident,
            ))
            if old and old in pack.objects[default_object].fields:
                changes.append(SchemaChange(
                    kind="rename_field", object=default_object, field=old, rename_to=new_ident,
                ))

    # split X into A and B
    for m in re.finditer(
        r"split\s+([a-z_][a-z0-9_]*)\s+into\s+([a-z_][a-z0-9_]*)\s+and\s+([a-z_][a-z0-9_]*)",
        text, re.IGNORECASE,
    ):
        old = m.group(1).lower()
        obj = _object_of_field(old, pack) or default_object
        changes.append(SchemaChange(
            kind="split_field", object=obj, field=old,
            into=[m.group(2).lower(), m.group(3).lower()],
        ))

    # rename X to Y
    for m in re.finditer(
        r"rename\s+([a-z_][a-z0-9_]*)\s+(?:to|into)\s+([a-z_][a-z0-9_]*)",
        text, re.IGNORECASE,
    ):
        old = m.group(1).lower()
        obj = _object_of_field(old, pack) or default_object
        changes.append(SchemaChange(
            kind="rename_field", object=obj, field=old, rename_to=m.group(2).lower(),
        ))

    # add [a|an] [<type>] field [called|named] <name>  /  add a <name> [<type>] field
    add_patterns = [
        r"add\s+a[n]?\s+(?P<type>\w+)?\s*field\s+(?:called|named)\s+['\"]?(?P<name>[a-z_][a-z0-9_ ]*)['\"]?",
        r"add\s+a[n]?\s+['\"]?(?P<name>[a-z_][a-z0-9_ ]*?)['\"]?\s+(?P<type>text|number|integer|int|date|datetime|enum|photo|image|boolean|bool|attachment|location)?\s*field",
    ]
    seen: set[str] = {c.field for c in changes}
    for pat in add_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            raw_name = (m.group("name") or "").strip().lower()
            name = re.sub(r"\s+", "_", raw_name).strip("_")
            if not name or name in seen:
                continue
            explicit = m.groupdict().get("type")
            if explicit and explicit.lower() in {"field"}:
                explicit = None
            ftype = _infer_type(name, explicit)
            changes.append(SchemaChange(
                kind="add_field", object=default_object, field=name, field_type=ftype,
            ))
            seen.add(name)
    return changes


def _target_object(text: str, pack: DomainPack) -> str:
    low = (text or "").lower()
    for obj in pack.objects:
        if re.search(rf"\b{re.escape(obj)}\b", low):
            return obj
    return next(iter(pack.objects))


def _object_of_field(field_name: str, pack: DomainPack) -> str | None:
    for obj_name, obj in pack.objects.items():
        if field_name in obj.fields:
            return obj_name
    return None


def build_plan(text: str, pack: DomainPack) -> HardeningPlan:
    changes = parse_edit(text, pack)
    if not changes:
        return HardeningPlan(
            domain=pack.name, object=next(iter(pack.objects)), changes=[],
            added_columns=[], renamed_columns=[], migration_sql="", summary=[],
            ok=False, error="could not parse a schema edit from the request",
        )
    target_obj = changes[0].object
    tname = table_name(pack.name, target_obj) if target_obj in pack.objects else table_name(pack.name, next(iter(pack.objects)))
    added: list[tuple[str, str]] = []
    renamed: list[tuple[str, str]] = []
    added_objects: list[str] = []
    added_caps: list[str] = []
    summary: list[str] = []
    sql_lines = [f"-- hardening migration for {pack.name}", "PRAGMA foreign_keys = ON;"]

    existing = set(pack.objects[target_obj].fields) if target_obj in pack.objects else set()
    for ch in changes:
        summary.append(ch.describe())
        if ch.kind == "add_object":
            if ch.object in pack.objects or ch.object in added_objects:
                continue
            if not _IDENT_RE.match(ch.object):
                continue
            added_objects.append(ch.object)
            ident = ch.field or "name"
            new_table = table_name(pack.name, ch.object)
            sql_lines.append(
                f"CREATE TABLE IF NOT EXISTS {new_table} ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "object_uid TEXT UNIQUE, entry_id TEXT, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
                "tombstoned INTEGER NOT NULL DEFAULT 0, "
                f"{ident} TEXT, notes TEXT);"
            )
            sql_lines.append(
                f"CREATE INDEX IF NOT EXISTS {new_table}_entry_idx ON {new_table}(entry_id);"
            )
        elif ch.kind == "add_capability":
            if ch.capability and ch.capability not in added_caps:
                added_caps.append(ch.capability)
            if ch.capability == "media":
                if "photos" not in existing and target_obj in pack.objects:
                    added.append(("photos", "TEXT"))
                    existing.add("photos")
                    sql_lines.append(f"ALTER TABLE {tname} ADD COLUMN photos TEXT;")
            elif ch.capability == "map":
                for col in ("lat", "lng"):
                    if col not in existing and target_obj in pack.objects:
                        added.append((col, "REAL"))
                        existing.add(col)
                        sql_lines.append(f"ALTER TABLE {tname} ADD COLUMN {col} REAL;")
        elif ch.kind == "identity":
            continue
        elif ch.kind == "add_field":
            if not _IDENT_RE.match(ch.field) or ch.field in existing:
                continue
            sqlt = _SQL_TYPE.get(ch.field_type, "TEXT")
            added.append((ch.field, sqlt))
            existing.add(ch.field)
            sql_lines.append(f"ALTER TABLE {tname} ADD COLUMN {ch.field} {sqlt};")
        elif ch.kind == "rename_field":
            if ch.field in existing and _IDENT_RE.match(ch.rename_to):
                renamed.append((ch.field, ch.rename_to))
                sql_lines.append(
                    f"ALTER TABLE {tname} RENAME COLUMN {ch.field} TO {ch.rename_to};"
                )
        elif ch.kind == "split_field":
            for new_field in ch.into:
                if _IDENT_RE.match(new_field) and new_field not in existing:
                    added.append((new_field, "TEXT"))
                    existing.add(new_field)
                    sql_lines.append(f"ALTER TABLE {tname} ADD COLUMN {new_field} TEXT;")

    if not added and not renamed and not added_objects and not added_caps:
        return HardeningPlan(
            domain=pack.name, object=target_obj, changes=changes,
            added_columns=[], renamed_columns=[], migration_sql="", summary=summary,
            ok=False, error="edit produced no applicable column changes",
        )
    return HardeningPlan(
        domain=pack.name, object=target_obj, changes=changes,
        added_columns=added, renamed_columns=renamed,
        added_objects=added_objects, added_capabilities=added_caps,
        migration_sql="\n".join(sql_lines) + "\n", summary=summary,
    )


def _next_migration_path(pack: DomainPack) -> Path:
    migrations_dir = pack.root / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(migrations_dir.glob(f"{pack.name}_*.sql"))
    next_n = 1
    if existing:
        m = re.search(rf"{re.escape(pack.name)}_(\d+)_", existing[-1].name)
        if m:
            next_n = int(m.group(1)) + 1
    return migrations_dir / f"{pack.name}_{next_n:03d}_hardening.sql"


def _bump_version(version: str) -> str:
    parts = version.split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        parts[1] = str(int(parts[1]) + 1)
        parts[2] = "0"
    except ValueError:
        return version
    return ".".join(parts[:3])


def apply_plan(
    workspace: Workspace, pack: DomainPack, plan: HardeningPlan, *, edit_text: str
) -> dict[str, Any]:
    """Apply a confirmed hardening plan: schema.yaml + migration + registry + fixture."""
    if not plan.ok:
        return {"applied": False, "error": plan.error}

    from domain_foundry_core.wizard.hardening_safety import create_snapshot

    snapshot_obj = plan.object if plan.object in pack.objects else next(iter(pack.objects))
    snapshot = create_snapshot(workspace, pack, snapshot_obj)

    schema_path = pack.root / "schema.yaml"
    schema_raw = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {"objects": {}}

    for ch in plan.changes:
        if ch.kind == "add_object":
            ident = ch.field or "name"
            schema_raw.setdefault("objects", {})[ch.object] = {
                "title_field": ident,
                "fields": {
                    ident: {"type": "text", "required": True},
                    "notes": {"type": "text"},
                },
            }
            _ensure_object_operations(pack, ch.object)
            continue
        obj_fields = schema_raw["objects"].setdefault(ch.object, {}).setdefault("fields", {})
        if ch.kind == "add_field" and ch.field not in obj_fields:
            entry: dict[str, Any] = {"type": ch.field_type}
            if ch.field_type == "enum":
                entry["values"] = []
                entry["allow_other"] = True
            obj_fields[ch.field] = entry
        elif ch.kind == "rename_field" and ch.field in obj_fields:
            obj_fields[ch.rename_to] = obj_fields.pop(ch.field)
            title_field = schema_raw["objects"][ch.object].get("title_field")
            if title_field == ch.field:
                schema_raw["objects"][ch.object]["title_field"] = ch.rename_to
        elif ch.kind == "split_field":
            for new_field in ch.into:
                obj_fields.setdefault(new_field, {"type": "text"})
        elif ch.kind == "identity":
            schema_raw["objects"][ch.object]["title_field"] = ch.field
            obj_fields.setdefault(ch.field, {"type": "text", "required": True})
        elif ch.kind == "add_capability":
            if ch.capability == "media":
                obj_fields.setdefault("photos", {"type": "attachment"})
            elif ch.capability == "map":
                obj_fields.setdefault("lat", {"type": "number"})
                obj_fields.setdefault("lng", {"type": "number"})
            _merge_capability(pack, ch.capability, ch.object)

    schema_path.write_text(
        yaml.safe_dump(schema_raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    # Bump pack version so the migration + schema_registry version advance.
    pack_path = pack.root / "pack.yaml"
    pack_raw = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
    new_version = _bump_version(str(pack_raw.get("version", "0.1.0")))
    pack_raw["version"] = new_version
    pack_path.write_text(
        yaml.safe_dump(pack_raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    # Write + execute the ALTER migration against domains.sqlite (idempotent).
    migration_path = _next_migration_path(pack)
    migration_path.write_text(plan.migration_sql, encoding="utf-8")
    _execute_alters(workspace, plan)

    # Reload the pack and refresh the schema registry / apply_policy / pack_install.
    reloaded = load_pack(pack.root, validate=True)
    apply_pack_schema(reloaded, workspace.domains_db, workspace.ledger_db)

    fixture = _append_fixture(workspace, reloaded, plan, edit_text)

    return {
        "applied": True,
        "domain": pack.name,
        "version": new_version,
        "migration": migration_path.name,
        "migration_path": str(migration_path),
        "added": [n for n, _ in plan.added_columns],
        "renamed": [{"from": o, "to": n} for o, n in plan.renamed_columns],
        "added_objects": list(plan.added_objects),
        "added_capabilities": list(plan.added_capabilities),
        "summary": plan.summary,
        "snapshot": snapshot,
        "fixture": fixture,
    }


def _execute_alters(workspace: Workspace, plan: HardeningPlan) -> None:
    conn = connect_rw(workspace.domains_db)
    try:
        if plan.migration_sql.strip():
            conn.executescript(plan.migration_sql)
        conn.commit()
    finally:
        conn.close()


def _append_fixture(
    workspace: Workspace, pack: DomainPack, plan: HardeningPlan, edit_text: str
) -> dict[str, Any]:
    """Append a routing example + eval_case asserting the new shape still routes."""
    routing_path = pack.root / "routing.yaml"
    routing_raw = yaml.safe_load(routing_path.read_text(encoding="utf-8")) or {}
    examples = routing_raw.setdefault("examples", [])
    rules = routing_raw.setdefault("rules", [])
    if plan.added_objects:
        obj = plan.added_objects[0]
        fixture_text = f"added a new {obj} to the catalog"
        examples.append({"text": fixture_text, "expect": {"object": obj, "operation": "create"}})
        rules.append({"match": re.escape(obj), "object": obj, "confidence_boost": 0.25})
    else:
        base_text = examples[0]["text"] if examples else f"logged a {plan.object}"
        new_field = plan.added_columns[0][0] if plan.added_columns else (
            plan.renamed_columns[0][1] if plan.renamed_columns else "field"
        )
        fixture_text = f"{base_text} — noting the {new_field.replace('_', ' ')}"
        examples.append({
            "text": fixture_text,
            "expect": {"object": plan.object, "operation": "create"},
        })
    routing_path.write_text(
        yaml.safe_dump(routing_raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    eval_id = append_eval_case(
        workspace,
        source="hardening",
        raw_text=fixture_text,
        expected={
            "captures": [
                {
                    "domain": pack.name,
                    "object_type": (plan.added_objects[0] if plan.added_objects else plan.object),
                    "operation": "create",
                }
            ]
        },
        context={"packs": [pack.name], "date": now_iso()[:10], "hardening_edit": edit_text},
    )
    return {"eval_case_id": eval_id, "example_text": fixture_text}


def _ensure_object_operations(pack: DomainPack, object_name: str) -> None:
    path = pack.root / "operations.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    raw = raw if isinstance(raw, dict) else {}
    raw.setdefault(object_name, ["create", "update", "correct", "delete"])
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _merge_capability(pack: DomainPack, capability: str, object_name: str) -> None:
    path = pack.root / "capabilities.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    raw = raw if isinstance(raw, dict) else {}
    caps = raw.setdefault("capabilities", {})
    compat = raw.setdefault("compatibility", {"core": ">=0.1,<2", "capabilities": {}})
    compat.setdefault("capabilities", {})
    views_path = pack.root / "projections.yaml"
    views_raw = yaml.safe_load(views_path.read_text(encoding="utf-8")) if views_path.is_file() else {}
    views_raw = views_raw if isinstance(views_raw, dict) else {}
    app = views_raw.setdefault("app", {})
    views = app.setdefault("views", [])
    if capability == "media":
        caps["media"] = {
            "version": 1,
            "galleries": [
                {
                    "id": "photos",
                    "title": "Gallery",
                    "object": object_name,
                    "field": "photos",
                    "source": "capture_attachments",
                    "accept": ["image/jpeg", "image/png", "image/webp"],
                }
            ],
        }
        compat["capabilities"]["media"] = ">=1,<2"
        if not any(v.get("block") == "gallery" for v in views):
            views.append(
                {
                    "id": f"{object_name}_gallery",
                    "title": "Gallery",
                    "block": "gallery",
                    "object": object_name,
                    "config": {"gallery": "photos"},
                }
            )
    elif capability == "map":
        if not any(v.get("block") == "map" for v in views):
            views.append(
                {
                    "id": f"{object_name}_map",
                    "title": "Map",
                    "block": "map",
                    "object": object_name,
                    "config": {},
                }
            )
    elif capability == "compare":
        caps.setdefault(
            "compare",
            {
                "version": 1,
                "comparisons": [
                    {"id": f"{object_name}_compare", "title": "Compare", "object": object_name}
                ],
            },
        )
        compat["capabilities"]["compare"] = ">=1,<2"
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    views_path.write_text(
        yaml.safe_dump(views_raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

