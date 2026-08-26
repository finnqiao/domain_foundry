"""Compile one FoundrySpec into an owned, evidence-backed application bundle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from domain_foundry_core.clock import now_iso

from .loader import DEFAULT_PRINCIPLES, DEFAULT_REGISTRY
from .models import EntitySpec, FoundrySpec, RelationshipSpec

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_SQL_TYPES = {
    "text": "TEXT",
    "integer": "INTEGER",
    "number": "REAL",
    "boolean": "INTEGER",
    "date": "TEXT",
    "datetime": "TEXT",
    "duration": "REAL",
    "enum": "TEXT",
    "attachment": "TEXT",
    "location": "TEXT",
    "json": "TEXT",
}
_ON_DELETE = {
    "restrict": "RESTRICT",
    "cascade": "CASCADE",
    "set_null": "SET NULL",
    "archive": "RESTRICT",
}
COMPILER_VERSION = "domain-foundry-core/foundry-spec-1.1"
DEFAULT_RUNTIME = Path(__file__).with_name("runtime.js")


@dataclass(frozen=True)
class BuildArtifact:
    root: Path
    app: Path
    schema: Path
    spec: Path
    evidence: Path
    receipt: Path


class FoundryCompiler:
    """Deep module: validated spec in, complete owned bundle out."""

    def compile(
        self,
        spec: FoundrySpec,
        destination: Path,
        *,
        generated_at: str | None = None,
    ) -> BuildArtifact:
        destination = destination.resolve()
        if destination.exists() and (
            not destination.is_dir() or any(destination.iterdir())
        ):
            raise FileExistsError(f"refusing to overwrite existing destination: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent)
        )

        try:
            generated_at = generated_at or now_iso()
            spec_json = spec.model_dump_json(indent=2)
            evidence_json = json.dumps(self.knowledge_snapshot(spec), indent=2, ensure_ascii=False)
            files = {
                "foundry-spec.json": spec_json + "\n",
                "schema.sql": self.compile_ddl(spec),
                "app.html": self.render_app(spec),
                "evidence.json": evidence_json + "\n",
                "README.md": self.render_readme(spec),
            }
            for name, content in files.items():
                (staging / name).write_text(content, encoding="utf-8")

            hashes = {
                name: hashlib.sha256(content.encode("utf-8")).hexdigest()
                for name, content in files.items()
            }
            receipt_payload = {
                "spec_id": spec.id,
                "spec_version": spec.spec_version,
                "generated_at": generated_at,
                "compiler": COMPILER_VERSION,
                "artifacts": hashes,
                "sources": spec.source_ids,
                "principles": spec.principle_ids,
                "generation": spec.generation.model_dump(mode="json") if spec.generation else None,
                # Lifted out of the nested receipt so pack metadata and UI copy
                # can read the tier without knowing the receipt's shape.
                "evidence_tier": spec.evidence_tier,
                "evidence_label": spec.evidence_tier_label,
            }
            (staging / "build-receipt.json").write_text(
                json.dumps(receipt_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            if destination.exists():
                destination.rmdir()
            os.replace(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        receipt = destination / "build-receipt.json"
        return BuildArtifact(
            root=destination,
            app=destination / "app.html",
            schema=destination / "schema.sql",
            spec=destination / "foundry-spec.json",
            evidence=destination / "evidence.json",
            receipt=receipt,
        )

    def knowledge_snapshot(self, spec: FoundrySpec) -> dict[str, Any]:
        registry = yaml.safe_load(DEFAULT_REGISTRY.read_text(encoding="utf-8")) or {}
        sources = [
            source
            for source in registry.get("sources", [])
            if source.get("id") in set(spec.source_ids)
        ]
        registered_ids = {str(source.get("id")) for source in sources}
        sources.extend(
            source.model_dump(mode="json")
            for source in spec.source_snapshots
            if source.id not in registered_ids
        )
        wanted_principles = set(spec.principle_ids)
        principles: list[dict[str, Any]] = []
        for path in sorted(DEFAULT_PRINCIPLES.glob("*.yaml")):
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            principles.extend(
                item
                for item in document.get("principles", [])
                if item.get("id") in wanted_principles
            )
        return {
            "snapshot_version": 1,
            "spec_id": spec.id,
            "sources": sources,
            "principles": principles,
            "citations": [item.model_dump(mode="json") for item in spec.evidence],
            "derivations": [item.model_dump(mode="json") for item in spec.derivations],
        }

    def compile_ddl(self, spec: FoundrySpec) -> str:
        prefix = self._sql_ident(spec.id.replace("-", "_"))
        entity_by_id = {entity.id: entity for entity in spec.domain.entities}
        inline_relationships: dict[str, list[RelationshipSpec]] = {}
        association_relationships: list[RelationshipSpec] = []
        for relationship in spec.domain.relationships:
            if relationship.cardinality in {"many_to_one", "one_to_one"}:
                inline_relationships.setdefault(relationship.from_entity, []).append(relationship)
            else:
                association_relationships.append(relationship)

        lines = [
            "-- generated from FoundrySpec 1.0; do not edit in place",
            "PRAGMA foreign_keys = ON;",
            "PRAGMA journal_mode = WAL;",
            "",
        ]
        for entity in spec.domain.entities:
            table = self._table(prefix, entity.id)
            columns = [
                "row_id INTEGER PRIMARY KEY AUTOINCREMENT",
                "object_uid TEXT NOT NULL UNIQUE",
                "captured_at TEXT NOT NULL",
                "updated_at TEXT NOT NULL",
                "tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1))",
            ]
            for field in entity.fields:
                name = self._sql_ident(field.name)
                sql_type = _SQL_TYPES[field.type]
                required = " NOT NULL" if field.required else ""
                checks: list[str] = []
                if field.type == "boolean":
                    checks.append(f"{name} IN (0, 1)")
                if field.type == "enum" and field.values:
                    values = ", ".join(self._sql_literal(value) for value in field.values)
                    checks.append(f"{name} IN ({values})")
                if field.type == "json":
                    json_check = f"json_valid({name})"
                    checks.append(json_check if field.required else f"{name} IS NULL OR {json_check}")
                suffix = f" CHECK ({' AND '.join(checks)})" if checks else ""
                columns.append(f"{name} {sql_type}{required}{suffix}")

            identity = ", ".join(self._sql_ident(name) for name in entity.identity)
            columns.append(f"CONSTRAINT uq_{entity.id}_identity UNIQUE ({identity})")
            for constraint in spec.domain.constraints:
                if constraint.entity != entity.id:
                    continue
                cname = self._sql_ident(constraint.id)
                fields = ", ".join(self._sql_ident(name) for name in constraint.fields)
                if constraint.kind == "unique":
                    columns.append(f"CONSTRAINT {cname} UNIQUE ({fields})")
                elif constraint.kind == "check" and constraint.expression:
                    columns.append(
                        f"CONSTRAINT {cname} CHECK ({self._safe_check(constraint.expression, entity)})"
                    )

            for relationship in inline_relationships.get(entity.id, []):
                target = entity_by_id[relationship.to_entity]
                local_field = self._relationship_field(entity, target)
                target_field = self._sql_ident(target.identity[0])
                target_table = self._table(prefix, target.id)
                columns.append(
                    f"CONSTRAINT {self._sql_ident(relationship.id)} "
                    f"FOREIGN KEY ({local_field}) REFERENCES {target_table}({target_field}) "
                    f"ON DELETE {_ON_DELETE[relationship.on_delete]}"
                )

            lines.append(f"CREATE TABLE IF NOT EXISTS {table} (")
            lines.append("    " + ",\n    ".join(columns))
            lines.append(");")
            lines.append(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_captured_at ON {table}(captured_at);"
            )
            lines.append("")

        for relationship in association_relationships:
            from_table = self._table(prefix, relationship.from_entity)
            to_table = self._table(prefix, relationship.to_entity)
            join_table = self._table(prefix, f"rel_{relationship.id}")
            lines.extend(
                [
                    f"CREATE TABLE IF NOT EXISTS {join_table} (",
                    "    from_uid TEXT NOT NULL,",
                    "    to_uid TEXT NOT NULL,",
                    "    captured_at TEXT NOT NULL,",
                    "    provenance_json TEXT NOT NULL CHECK (json_valid(provenance_json)),",
                    f"    FOREIGN KEY (from_uid) REFERENCES {from_table}(object_uid) ON DELETE RESTRICT,",
                    f"    FOREIGN KEY (to_uid) REFERENCES {to_table}(object_uid) ON DELETE RESTRICT,",
                    "    PRIMARY KEY (from_uid, to_uid)",
                    ");",
                    "",
                ]
            )

        for index in spec.domain.indexes:
            table = self._table(prefix, index.entity)
            fields = ", ".join(self._sql_ident(name) for name in index.fields)
            unique = "UNIQUE " if index.unique else ""
            lines.append(
                f"CREATE {unique}INDEX IF NOT EXISTS {self._sql_ident(index.id)} "
                f"ON {table}({fields});"
            )
        lines.append("")
        return "\n".join(lines)

    def render_app(self, spec: FoundrySpec) -> str:
        app_payload = spec.model_dump(mode="json")
        app_payload["_source_records"] = self.knowledge_snapshot(spec)["sources"]
        payload = json.dumps(app_payload, ensure_ascii=False).replace("</", "<\\/")
        template = _APP_TEMPLATE.replace("__TITLE__", _html_text(spec.title))
        runtime = DEFAULT_RUNTIME.read_text(encoding="utf-8").replace("</", "<\\/")
        return template.replace("__SPEC_JSON__", payload).replace("__RUNTIME_JS__", runtime)

    def render_readme(self, spec: FoundrySpec) -> str:
        return textwrap.dedent(
            f"""\
            # {spec.title}

            This application was compiled from `foundry-spec.json`. Its preview
            and final local application are the same `app.html` artifact.

            Research for this build is **{spec.evidence_tier_label}**.

            ## Open

            Open `app.html` directly in a modern browser. New records, immutable
            prior versions, and receipts are stored in browser local storage.
            **Export data** creates a complete JSON backup; **Restore backup**
            validates the spec identity before replacing local state.

            ## Data model

            `schema.sql` is SQLite DDL with identities, constraints, foreign
            keys, relationship tables, and workload-derived indexes. Apply it
            to a new database with foreign keys enabled.

            ## Ownership

            - `foundry-spec.json` — complete product and derivation contract
            - `evidence.json` — frozen source, principle, citation, and derivation snapshot
            - `build-receipt.json` — artifact hashes and compiler identity
            - `schema.sql` — executable local data model
            - `app.html` — self-contained local application, correction history,
              and validated JSON export/restore

            Generated output is MIT-licensed with Domain Foundry unless an
            evidence or dependency record states otherwise. Reference-only
            sources informed facts and patterns; their code and imagery are not
            copied into this bundle.
            """
        )

    @staticmethod
    def _relationship_field(entity: EntitySpec, target: EntitySpec) -> str:
        fields = {field.name for field in entity.fields}
        candidates = [f"{target.id}_id", target.identity[0]]
        for candidate in candidates:
            if candidate in fields:
                return FoundryCompiler._sql_ident(candidate)
        raise ValueError(
            f"relationship from {entity.id} to {target.id} needs a local identity field"
        )

    @staticmethod
    def _safe_check(expression: str, entity: EntitySpec) -> str:
        if any(token in expression for token in (";", "--", "/*", "*/")):
            raise ValueError("unsafe check expression")
        if not re.fullmatch(r"[A-Za-z0-9_ .<>=!()+\-*/'\"]+", expression):
            raise ValueError("unsupported check expression")
        words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression))
        allowed = {field.name for field in entity.fields} | {"AND", "OR", "NOT", "NULL"}
        unknown = {word for word in words if word not in allowed and word.upper() not in allowed}
        if unknown:
            raise ValueError(f"check expression uses unknown identifiers: {sorted(unknown)}")
        return expression

    @staticmethod
    def _sql_ident(value: str) -> str:
        if not _IDENT_RE.fullmatch(value):
            raise ValueError(f"unsafe SQL identifier: {value!r}")
        return value

    @staticmethod
    def _table(prefix: str, entity: str) -> str:
        return FoundryCompiler._sql_ident(f"{prefix}__{entity}")

    @staticmethod
    def _sql_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"


def _html_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_APP_TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
  <title>__TITLE__</title>
  <style>
    * { box-sizing: border-box; }
    :root {
      --bg: #f3f0e8; --surface: #fffdf8; --ink: #1c1c1a; --muted: #65645f;
      --accent: #965131; --accent-alt: #315866; --border: #d1c9ba;
      --focus: #17627c; --danger: #a53a35; --radius: 10px;
      --shadow: 0 14px 40px rgba(32, 28, 22, .12);
      font-family: "Avenir Next", "Segoe UI", sans-serif;
    }
    html { background: var(--bg); color: var(--ink); }
    body { margin: 0; min-height: 100vh; background: var(--bg); }
    button, input, select, textarea { font: inherit; }
    button { min-height: 44px; cursor: pointer; }
    button:disabled { cursor: not-allowed; opacity: .58; }
    button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible {
      outline: 3px solid var(--focus); outline-offset: 3px;
    }
    .skip { position: fixed; left: 1rem; top: -5rem; z-index: 20; background: var(--ink); color: var(--surface); padding: .7rem 1rem; }
    .skip:focus { top: 1rem; }
    .app { min-height: 100vh; display: grid; grid-template-columns: minmax(210px, 260px) 1fr; }
    .rail { min-height: 100vh; padding: 2rem 1.25rem; border-right: 1px solid var(--border); background: color-mix(in srgb, var(--surface) 72%, var(--bg)); position: sticky; top: 0; align-self: start; }
    .brand { margin: 0 0 2.5rem; font-size: clamp(1.6rem, 3vw, 2.5rem); line-height: .98; letter-spacing: -.035em; max-width: 8ch; }
    .world { color: var(--muted); line-height: 1.45; margin: -.9rem 0 2rem; }
    .view-nav { display: grid; gap: .25rem; }
    .view-nav button { text-align: left; padding: .7rem .8rem; border: 0; border-radius: calc(var(--radius) - 3px); color: var(--ink); background: transparent; }
    .view-nav button:hover { background: var(--surface); }
    .view-nav button[aria-current="page"] { background: var(--ink); color: var(--surface); }
    .rail-foot { margin-top: 2.5rem; font-size: .82rem; color: var(--muted); }
    main { min-width: 0; padding: clamp(1.25rem, 4vw, 3.75rem); }
    .topbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 2rem; padding-bottom: 2rem; border-bottom: 1px solid var(--border); }
    .topbar h1 { margin: 0; font-size: clamp(2.4rem, 7vw, 5.7rem); line-height: .92; letter-spacing: -.04em; max-width: 11ch; text-wrap: balance; }
    .topbar p { max-width: 65ch; color: var(--muted); }
    .toolbar { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: .55rem; }
    .button { border: 1px solid var(--border); background: var(--surface); color: var(--ink); border-radius: calc(var(--radius) - 2px); padding: .65rem .9rem; }
    .button:hover { border-color: var(--ink); }
    .button.primary { background: var(--accent); color: #fff; border-color: transparent; }
    .button.danger { color: var(--danger); }
    .view-head { margin: 3.5rem 0 2rem; display: grid; grid-template-columns: minmax(0, 1fr) minmax(220px, 32rem); gap: 2rem; align-items: end; }
    .view-head h2 { margin: 0; font-size: clamp(2rem, 5vw, 4rem); line-height: 1; letter-spacing: -.035em; }
    .view-head p { margin: 0; color: var(--muted); max-width: 70ch; }
    .regions { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 1rem; }
    .region { grid-column: span var(--span); min-width: 0; padding: clamp(1rem, 2.4vw, 2rem); background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow); }
    .region.support { background: transparent; box-shadow: none; border: 1px solid var(--border); }
    .region h3 { margin: 0 0 1.4rem; font-size: 1.1rem; }
    .region-meta { color: var(--muted); font-size: .78rem; margin: -.9rem 0 1.4rem; }
    .record-list { list-style: none; margin: 0; padding: 0; display: grid; gap: .7rem; }
    .record { padding: .85rem 0; border-top: 1px solid var(--border); min-width: 0; }
    .record:first-child { border-top: 0; padding-top: 0; }
    .record strong { display: block; font-size: 1.05rem; margin-bottom: .25rem; }
    .record-select { width: 100%; min-height: 0; padding: .45rem; margin: -.45rem; border: 0; border-radius: calc(var(--radius) - 4px); background: transparent; color: inherit; text-align: start; }
    .record-select:hover { background: color-mix(in srgb, var(--accent) 7%, transparent); }
    .record-select[aria-pressed="true"] { background: color-mix(in srgb, var(--accent) 12%, transparent); outline: 1px solid var(--accent); }
    .record dl, .detail-grid { margin: .6rem 0 0; display: grid; grid-template-columns: minmax(7rem, .7fr) minmax(0, 1.3fr); gap: .3rem .8rem; }
    dt { color: var(--muted); } dd { margin: 0; overflow-wrap: anywhere; }
    .canvas-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(105px, 1fr)); gap: .65rem; }
    .slot { aspect-ratio: .72; padding: .65rem; background: color-mix(in srgb, var(--accent) 8%, var(--surface)); border: 1px solid var(--border); border-radius: calc(var(--radius) - 3px); display: flex; flex-direction: column; justify-content: space-between; }
    .slot.empty { background: transparent; border-style: dashed; color: var(--muted); }
    .slot-number { font-variant-numeric: tabular-nums; font-size: .75rem; color: var(--muted); }
    .session-card { min-height: 20rem; display: grid; place-items: center; text-align: center; padding: 3rem 1rem; }
    .session-card .cue { font-size: clamp(2.7rem, 9vw, 7rem); line-height: 1; letter-spacing: -.03em; }
    .session-answer { margin-top: 2rem; font-size: 1.15rem; }
    .measure { font-family: ui-monospace, "SFMono-Regular", monospace; font-variant-numeric: tabular-nums; }
    .timeline { border-inline-start: 1px solid var(--accent-alt); padding-inline-start: 1rem; }
    .timeline .record { position: relative; }
    .timeline .record::before { content: ""; position: absolute; width: 9px; height: 9px; border-radius: 50%; background: var(--accent-alt); inset-inline-start: calc(-1rem - 5px); top: 1.1rem; }
    .timeline time { display: block; color: var(--muted); font-size: .78rem; margin-bottom: .35rem; }
    .chart-figure { margin: 0; }
    .chart-figure svg { display: block; width: 100%; min-height: 220px; overflow: visible; }
    .chart-grid { stroke: var(--border); stroke-width: 1; }
    .chart-area { fill: color-mix(in srgb, var(--accent) 14%, transparent); }
    .chart-line { fill: none; stroke: var(--accent); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
    .chart-point { fill: var(--surface); stroke: var(--accent); stroke-width: 3; }
    .chart-figure figcaption { color: var(--muted); font-size: .82rem; margin-top: .7rem; }
    .data-table-wrap { max-width: 100%; overflow-x: auto; }
    .data-table { width: 100%; border-collapse: collapse; font-size: .9rem; }
    .data-table th, .data-table td { padding: .65rem .7rem; border-bottom: 1px solid var(--border); text-align: start; vertical-align: top; overflow-wrap: anywhere; }
    .data-table th { color: var(--muted); font-size: .76rem; font-weight: 650; }
    .data-table tbody tr[aria-selected="true"] { background: color-mix(in srgb, var(--accent) 10%, transparent); }
    .data-table tbody tr { cursor: pointer; }
    .shelf-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: .8rem; }
    .shelf-item { min-height: 8rem; padding: 1rem; border: 1px solid var(--border); border-radius: calc(var(--radius) - 3px); background: color-mix(in srgb, var(--surface) 84%, var(--accent-alt)); color: var(--ink); text-align: start; }
    .shelf-item[aria-pressed="true"] { outline: 2px solid var(--accent); outline-offset: 2px; }
    .shelf-item small { display: block; color: var(--muted); margin-top: .7rem; }
    .workbench { display: grid; grid-template-columns: minmax(0, .8fr) minmax(0, 1.2fr); gap: 1rem; }
    .workbench aside { border-inline-end: 1px solid var(--border); padding-inline-end: 1rem; }
    .explanation { max-width: 68ch; }
    .explanation strong { display: block; margin-bottom: .55rem; }
    .storage-note { color: var(--muted); font-size: .78rem; margin: .8rem 0 0; }
    .empty-state { min-height: 12rem; display: grid; align-content: center; justify-items: start; gap: .75rem; color: var(--muted); }
    .empty-state p { max-width: 45ch; margin: 0; }
    .view-actions { display: flex; flex-wrap: wrap; gap: .6rem; margin-top: 1.2rem; }
    .status { min-height: 1.5rem; margin-top: 1rem; color: var(--ink); font-weight: 650; }
    .error { min-height: 1.5rem; margin-top: .35rem; color: var(--danger); font-weight: 650; }
    dialog { width: min(680px, calc(100vw - 2rem)); max-height: calc(100vh - 2rem); border: 0; border-radius: var(--radius); padding: 0; color: var(--ink); background: var(--surface); box-shadow: 0 24px 80px rgba(0,0,0,.28); }
    dialog::backdrop { background: rgba(18, 17, 14, .68); }
    .dialog-inner { padding: clamp(1.2rem, 4vw, 2.5rem); }
    .dialog-head { display: flex; justify-content: space-between; gap: 1rem; align-items: start; }
    .dialog-head h2 { margin: 0; font-size: 2rem; letter-spacing: -.03em; }
    .icon-button { width: 44px; padding: 0; border: 1px solid var(--border); border-radius: 50%; background: transparent; }
    .form-grid { margin-top: 1.5rem; display: grid; gap: 1rem; }
    label { display: grid; gap: .35rem; font-weight: 650; }
    label small { color: var(--muted); font-weight: 400; }
    input, select, textarea { width: 100%; min-height: 44px; padding: .65rem .7rem; border: 1px solid var(--border); border-radius: calc(var(--radius) - 3px); background: var(--bg); color: var(--ink); }
    textarea { min-height: 7rem; resize: vertical; }
    .dialog-actions { margin-top: 1.5rem; display: flex; justify-content: flex-end; gap: .6rem; }
    .evidence-item { padding: 1rem 0; border-top: 1px solid var(--border); }
    .evidence-item a { color: var(--accent-alt); }
    .visually-hidden { position: absolute !important; width: 1px !important; height: 1px !important; padding: 0 !important; margin: -1px !important; overflow: hidden !important; clip: rect(0, 0, 0, 0) !important; white-space: nowrap !important; border: 0 !important; }
    body[data-topology="session"] .app { grid-template-columns: 1fr; }
    body[data-topology="session"] .rail { min-height: auto; position: static; border-right: 0; border-bottom: 1px solid var(--border); display: grid; grid-template-columns: auto 1fr; gap: 2rem; padding: 1rem clamp(1rem, 4vw, 3rem); align-items: center; }
    body[data-topology="session"] .brand { margin: 0; max-width: none; font-size: 1.15rem; }
    body[data-topology="session"] .world, body[data-topology="session"] .rail-foot { display: none; }
    body[data-topology="session"] .view-nav { display: flex; justify-content: flex-end; overflow-x: auto; }
    body[data-topology="session"] main { width: min(1100px, 100%); margin: auto; }
    @media (max-width: 820px) {
      .app { grid-template-columns: 1fr; min-width: 0; width: 100%; }
      .rail { min-width: 0; width: 100%; max-width: 100vw; min-height: auto; position: static; border-right: 0; border-bottom: 1px solid var(--border); padding: 1rem; overflow: hidden; }
      .brand { max-width: none; margin: 0 0 .3rem; font-size: 1.4rem; }
      .world, .rail-foot { display: none; }
      .view-nav { display: flex; min-width: 0; width: 100%; max-width: calc(100vw - 2rem); overflow-x: auto; padding-bottom: .2rem; }
      .view-nav button { flex: 0 0 auto; }
      main { min-width: 0; width: 100%; }
      .topbar, .view-head { grid-template-columns: 1fr; display: grid; }
      .toolbar { justify-content: flex-start; }
      .region { grid-column: 1 / -1 !important; }
      .record dl, .detail-grid { grid-template-columns: 1fr; }
      .workbench { grid-template-columns: 1fr; }
      .workbench aside { border-inline-end: 0; border-bottom: 1px solid var(--border); padding-inline-end: 0; padding-bottom: 1rem; }
      body[data-topology="session"] .rail { display: block; padding: 1rem; }
      body[data-topology="session"] .brand { margin-bottom: .8rem; }
      body[data-topology="session"] .view-nav { justify-content: flex-start; max-width: calc(100vw - 2rem); }
    }
    @media (prefers-reduced-motion: no-preference) {
      .region { animation: resolve-in 420ms cubic-bezier(.16,1,.3,1) both; }
      @keyframes resolve-in { from { opacity: .6; transform: translateY(8px); filter: blur(3px); } to { opacity: 1; transform: none; filter: none; } }
    }
  </style>
</head>
<body>
  <a class="skip" href="#main">Skip to application</a>
  <div id="app"></div>
  <dialog id="capture-dialog" aria-labelledby="capture-title"><div class="dialog-inner" id="capture-content"></div></dialog>
  <dialog id="evidence-dialog" aria-labelledby="evidence-title"><div class="dialog-inner" id="evidence-content"></div></dialog>
  <script type="application/json" id="foundry-spec">__SPEC_JSON__</script>
  <script>
__RUNTIME_JS__
  </script>
</body>
</html>
'''


__all__ = ["BuildArtifact", "FoundryCompiler"]
