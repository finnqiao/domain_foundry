"""Generic mapping-config-driven importer.

Writes ``capture_event`` / ``entry`` / ``canonical_object`` (+ domains row)
preserving original timestamps and a stable ``source_ref``. Idempotent on
``(channel, source_ref)`` — re-runs are no-ops counted as ``skipped_existing``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from domain_foundry_core.apply.journal import (
    ensure_canonical_object,
    insert_source_link,
    write_object_revision,
)
from domain_foundry_core.clock import now_iso
from domain_foundry_core.ids import canonical_uid, new_ulid
from domain_foundry_core.ledger.migrate import ensure_migrated
from domain_foundry_core.migrations.importers.config import (
    EntityMapping,
    MappingConfig,
    load_mapping,
    render_template,
)
from domain_foundry_core.migrations.importers.models import (
    ReconciliationReport,
    RecordOutcome,
)
from domain_foundry_core.migrations.importers.source import SourceDriver
from domain_foundry_core.packs.models import DomainPack, FieldSpec, ObjectSpec
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.packs.schema_compiler import table_name
from domain_foundry_core.paths import Workspace
from domain_foundry_core.search.fts import set_canonical_searchable_text
from domain_foundry_core.security.redact import redact_secrets
from domain_foundry_core.security.store import connect_rw, last_row_id

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class GenericImporter:
    """Mapping-config-driven provenance-preserving importer."""

    def __init__(
        self,
        workspace: Workspace,
        mapping: MappingConfig | Path | str,
        *,
        registry: PackRegistry | None = None,
        dry_run: bool = True,
        actor: str = "importer",
    ) -> None:
        self.ws = workspace
        self.ws.ensure_layout()
        ensure_migrated(self.ws.ledger_db, "ledger")
        ensure_migrated(self.ws.domains_db, "domains")
        if isinstance(mapping, MappingConfig):
            self.mapping = mapping
        else:
            self.mapping = load_mapping(mapping)
        self.registry = registry or PackRegistry(self.ws)
        self.dry_run = dry_run
        self.actor = actor

    def run(self, source: SourceDriver) -> ReconciliationReport:
        report = ReconciliationReport(
            mapping_name=self.mapping.name,
            channel=self.mapping.channel,
            dry_run=self.dry_run,
        )
        # Ensure pack schemas exist before apply writes.
        if not self.dry_run:
            self.registry.reload()
            self.registry.ensure_schemas_applied()

        for entity in self.mapping.entities:
            records = list(source.iter_records(entity.name))
            report.source_total += len(records)
            for record in records:
                outcome = self._import_one(entity, record)
                report.record(outcome)
        return report

    # ------------------------------------------------------------------ one row
    def _import_one(self, entity: EntityMapping, record: dict[str, Any]) -> RecordOutcome:
        source_id = record.get(entity.id_field)
        try:
            source_ref = self._source_ref(entity, record, source_id)
        except Exception as exc:  # noqa: BLE001
            return RecordOutcome(
                entity=entity.name,
                source_ref=None,
                source_id=source_id,
                kind="skipped_invalid",
                reason=f"source_ref: {exc}",
            )

        missing = [
            f for f in entity.required_source_fields if not _present(record.get(f))
        ]
        if missing:
            return RecordOutcome(
                entity=entity.name,
                source_ref=source_ref,
                source_id=source_id,
                kind="skipped_invalid",
                reason=f"missing required fields: {', '.join(missing)}",
            )

        pack = self.registry.get(entity.domain)
        if pack is None:
            return RecordOutcome(
                entity=entity.name,
                source_ref=source_ref,
                source_id=source_id,
                kind="failed",
                reason=(
                    f"no pack installed for domain {entity.domain!r} "
                    "(activate via PackRegistry.activate_bundled first)"
                ),
            )
        if entity.object_type not in pack.objects:
            return RecordOutcome(
                entity=entity.name,
                source_ref=source_ref,
                source_id=source_id,
                kind="failed",
                reason=(
                    f"object_type {entity.object_type!r} not in pack {entity.domain!r}"
                ),
            )

        existing = self._lookup_existing(source_ref)
        if existing:
            return RecordOutcome(
                entity=entity.name,
                source_ref=source_ref,
                source_id=source_id,
                kind="skipped_existing",
                reason="source_ref already imported",
                capture_event_id=existing["capture_event_id"],
                entry_id=existing["entry_id"],
                object_uid=existing.get("object_uid"),
            )

        if self.dry_run:
            return RecordOutcome(
                entity=entity.name,
                source_ref=source_ref,
                source_id=source_id,
                kind="would_import",
                reason="dry_run",
            )

        try:
            return self._write(entity, pack, record, source_ref, source_id)
        except Exception as exc:  # noqa: BLE001
            return RecordOutcome(
                entity=entity.name,
                source_ref=source_ref,
                source_id=source_id,
                kind="failed",
                reason=str(exc),
            )

    def _source_ref(
        self, entity: EntityMapping, record: dict[str, Any], source_id: Any
    ) -> str:
        if source_id is None or source_id == "":
            raise ValueError(f"missing id field {entity.id_field!r}")
        ref = render_template(entity.source_ref_template, record, id_value=source_id)
        ref = ref.strip()
        if not ref:
            raise ValueError("empty source_ref")
        return ref

    def _lookup_existing(self, source_ref: str) -> dict[str, Any] | None:
        conn = connect_rw(self.ws.ledger_db)
        try:
            row = conn.execute(
                """
                SELECT c.id AS capture_event_id, e.id AS entry_id
                FROM capture_event c
                JOIN entry e ON e.capture_event_id = c.id
                WHERE c.channel = ? AND c.source_ref = ?
                ORDER BY e.created_at ASC
                LIMIT 1
                """,
                (self.mapping.channel, source_ref),
            ).fetchone()
            if not row:
                return None
            link = conn.execute(
                """
                SELECT target_id AS object_uid
                FROM source_link
                WHERE source_type = 'entry' AND source_id = ?
                  AND target_type = 'canonical_object'
                ORDER BY id ASC
                LIMIT 1
                """,
                (row["entry_id"],),
            ).fetchone()
            return {
                "capture_event_id": row["capture_event_id"],
                "entry_id": row["entry_id"],
                "object_uid": link["object_uid"] if link else None,
            }
        finally:
            conn.close()

    def _write(
        self,
        entity: EntityMapping,
        pack: DomainPack,
        record: dict[str, Any],
        source_ref: str,
        source_id: Any,
    ) -> RecordOutcome:
        obj = pack.objects[entity.object_type]
        fields = self._map_fields(entity, obj, record)
        raw_text = self._raw_text(entity, record, fields)
        safe_text = redact_secrets(raw_text)
        captured_at = self._timestamp(entity, record)
        updated_at = self._updated_at(entity, record, fallback=captured_at)
        actor = self._actor(entity, record)
        summary = _summarize(safe_text)
        tname = table_name(pack.name, entity.object_type)
        object_uid = canonical_uid(pack.name, entity.object_type)
        capture_id = new_ulid()
        entry_id = new_ulid()
        import_now = now_iso()  # wall for outbox / non-provenance stamps

        title_field = obj.title_field
        natural_key = None
        if title_field and title_field in fields and fields[title_field]:
            natural_key = f"{pack.name}:{entity.object_type}:{fields[title_field]}"

        ledger = connect_rw(self.ws.ledger_db)
        domains = connect_rw(self.ws.domains_db)
        try:
            # Race-safe idempotency: UNIQUE(channel, source_ref)
            try:
                ledger.execute(
                    """
                    INSERT INTO capture_event (
                        id, channel, source_ref, actor, raw_text, raw_payload_json,
                        attachments_json, content_hash, captured_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        capture_id,
                        self.mapping.channel,
                        source_ref,
                        actor,
                        safe_text,
                        json.dumps(
                            {"import": self.mapping.name, "source_id": source_id},
                            sort_keys=True,
                            default=str,
                        ),
                        _content_hash(safe_text),
                        captured_at,
                        captured_at,
                    ),
                )
            except sqlite3.IntegrityError:
                ledger.rollback()
                existing = self._lookup_existing(source_ref)
                if existing:
                    return RecordOutcome(
                        entity=entity.name,
                        source_ref=source_ref,
                        source_id=source_id,
                        kind="skipped_existing",
                        reason="source_ref already imported (race)",
                        capture_event_id=existing["capture_event_id"],
                        entry_id=existing["entry_id"],
                        object_uid=existing.get("object_uid"),
                    )
                raise

            ledger.execute(
                """
                INSERT INTO entry (
                    id, capture_event_id, status, domain, object_type, operation,
                    routing_confidence, fallback_tier, summary, privacy_level,
                    tags_json, created_at, updated_at
                ) VALUES (?, ?, 'applied', ?, ?, 'create', 1.0, NULL, ?, 'normal',
                          ?, ?, ?)
                """,
                (
                    entry_id,
                    capture_id,
                    entity.domain,
                    entity.object_type,
                    summary,
                    json.dumps(["imported"], sort_keys=True),
                    captured_at,
                    updated_at,
                ),
            )
            ledger.execute(
                """
                INSERT INTO source_link (
                    source_type, source_id, target_type, target_id,
                    relationship, confidence, created_at
                ) VALUES ('capture_event', ?, 'entry', ?, 'created_from', 1.0, ?)
                """,
                (capture_id, entry_id, captured_at),
            )

            cols = ["object_uid", "entry_id", "created_at", "updated_at", "tombstoned"]
            vals: list[Any] = [object_uid, entry_id, captured_at, updated_at, 0]
            for fname, value in fields.items():
                if not _IDENT_RE.match(fname):
                    continue
                cols.append(fname)
                vals.append(value)
            placeholders = ", ".join("?" for _ in cols)
            col_sql = ", ".join(cols)
            cur = domains.execute(
                f"INSERT INTO {tname} ({col_sql}) VALUES ({placeholders})",
                vals,
            )
            row_id = last_row_id(cur)

            canonical = ensure_canonical_object(
                ledger,
                domain=pack.name,
                object_type=entity.object_type,
                store="domains",
                table_name=tname,
                row_id=row_id,
                natural_key=natural_key,
                now=captured_at,
                uid=object_uid,
            )
            # Preserve original timestamps on the journal row (ensure_* stamps now).
            ledger.execute(
                """
                UPDATE canonical_object
                SET created_at = ?, updated_at = ?
                WHERE uid = ?
                """,
                (captured_at, updated_at, canonical.uid),
            )
            after = domains.execute(
                f"SELECT * FROM {tname} WHERE id = ?", (row_id,)
            ).fetchone()
            write_object_revision(
                ledger,
                object_uid=canonical.uid,
                change_request_id=None,
                before_row=None,
                after_row=after,
                actor=actor or self.actor,
                actor_channel=self.mapping.channel,
                now=captured_at,
                force_diff={k: {"from": None, "to": v} for k, v in fields.items()},
            )
            insert_source_link(
                ledger,
                source_type="entry",
                source_id=entry_id,
                target_uid=canonical.uid,
                relationship="created_from",
                now=captured_at,
            )
            # Also link the external source_ref for reconciliation joins.
            insert_source_link(
                ledger,
                source_type="import",
                source_id=source_ref,
                target_uid=canonical.uid,
                relationship="imported_from",
                now=captured_at,
            )
            set_canonical_searchable_text(
                ledger, canonical.uid, fields, now=updated_at
            )
            from domain_foundry_core.apply.journal import schedule_projection_stub

            schedule_projection_stub(
                ledger,
                object_key=f"{pack.name}:{entity.object_type}",
                change_request_id=None,
                now=import_now,
                reason="import",
            )

            ledger.commit()
            domains.commit()
            return RecordOutcome(
                entity=entity.name,
                source_ref=source_ref,
                source_id=source_id,
                kind="imported",
                capture_event_id=capture_id,
                entry_id=entry_id,
                object_uid=canonical.uid,
            )
        except Exception:
            ledger.rollback()
            domains.rollback()
            raise
        finally:
            ledger.close()
            domains.close()

    # --------------------------------------------------------------- field map
    def _map_fields(
        self, entity: EntityMapping, obj: ObjectSpec, record: dict[str, Any]
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for dest, src in entity.field_map.items():
            if dest not in obj.fields:
                continue
            if src not in record:
                continue
            value = record[src]
            if value is None:
                continue
            out[dest] = _coerce(obj.fields[dest], value)
        # Apply pack defaults for required fields not supplied.
        for fname, fspec in obj.fields.items():
            if fname in out:
                continue
            if fspec.default == "capture_time":
                out[fname] = self._timestamp(entity, record)
            elif fspec.default is not None:
                out[fname] = fspec.default
        return out

    def _raw_text(
        self,
        entity: EntityMapping,
        record: dict[str, Any],
        fields: dict[str, Any],
    ) -> str:
        if entity.raw_text_field and entity.raw_text_field in record:
            value = record[entity.raw_text_field]
            if value is not None:
                return str(value)
        if entity.raw_text_template:
            return render_template(
                entity.raw_text_template,
                {**record, **fields},
                id_value=record.get(entity.id_field),
            )
        # Fallback: join mapped field values.
        parts = [str(v) for v in fields.values() if v not in (None, "")]
        return " ".join(parts) if parts else f"imported:{entity.name}:{record.get(entity.id_field)}"

    def _timestamp(self, entity: EntityMapping, record: dict[str, Any]) -> str:
        raw = record.get(entity.timestamp_field)
        if raw is None or raw == "":
            return now_iso()
        return str(raw)

    def _updated_at(
        self, entity: EntityMapping, record: dict[str, Any], *, fallback: str
    ) -> str:
        if not entity.updated_at_field:
            return fallback
        raw = record.get(entity.updated_at_field)
        if raw is None or raw == "":
            return fallback
        return str(raw)

    def _actor(self, entity: EntityMapping, record: dict[str, Any]) -> str | None:
        if entity.actor_field and entity.actor_field in record:
            value = record[entity.actor_field]
            if value is not None and str(value).strip():
                return str(value)
        return entity.default_actor or self.actor


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _content_hash(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _summarize(text: str, max_len: int = 120) -> str:
    one_line = " ".join(text.strip().split())
    if len(one_line) <= max_len:
        return one_line
    return one_line[: max_len - 1] + "…"


def _coerce(fspec: FieldSpec, value: Any) -> Any:
    if fspec.type == "number":
        return float(value)
    if fspec.type == "integer":
        return int(value)
    if fspec.type == "boolean":
        if isinstance(value, bool):
            return int(value)
        return int(bool(value))
    if fspec.type == "attachment" and fspec.many and not isinstance(value, str):
        return json.dumps(value)
    return value
