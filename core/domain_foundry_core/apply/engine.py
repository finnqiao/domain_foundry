"""Generic declarative ApplyEngine — executes pack operations.yaml against compiled schemas."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from domain_foundry_core.apply.journal import (
    ensure_canonical_object,
    insert_source_link,
    row_to_dict,
    schedule_projection_stub,
    write_object_revision,
)
from domain_foundry_core.clock import now_iso
from domain_foundry_core.ids import canonical_uid
from domain_foundry_core.packs.models import DomainPack, FieldSpec, ObjectSpec
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.packs.schema_compiler import table_name
from domain_foundry_core.paths import Workspace
from domain_foundry_core.search.fts import set_canonical_searchable_text
from domain_foundry_core.security.store import connect_rw, last_row_id

logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
ALLOWED_OPS = frozenset({"create", "update", "correct", "merge", "delete"})
# Schema `default:` tokens the engine resolves itself — a model that echoes one
# back as a field value must not have it stored verbatim.
_DEFAULT_TOKENS = frozenset({"capture_time", "now"})


@dataclass
class OperationSpec:
    domain: str
    operation: str
    object_type: str
    object_uid: str | None = None
    merge_into_uid: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    entry_id: str | None = None
    channel: str | None = None


@dataclass
class ApplyResult:
    ok: bool
    object_uid: str | None = None
    row_id: int | None = None
    revision: int | None = None
    created: bool = False
    operation: str = ""
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class ApplyEngine:
    """Channel-agnostic apply against domains.sqlite + ledger journal."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        registry: PackRegistry | None = None,
    ) -> None:
        self.ws = workspace
        self.registry = registry or PackRegistry(workspace)

    def apply_spec(
        self,
        spec: OperationSpec,
        *,
        change_request_id: int | None = None,
        actor: str = "system",
        actor_channel: str | None = None,
        ledger_conn: sqlite3.Connection | None = None,
        domains_conn: sqlite3.Connection | None = None,
    ) -> ApplyResult:
        try:
            self.validate(spec)
        except ValueError as exc:
            return ApplyResult(ok=False, operation=spec.operation, error=str(exc))

        owns_ledger = ledger_conn is None
        owns_domains = domains_conn is None
        ledger = ledger_conn or connect_rw(self.ws.ledger_db)
        domains = domains_conn or connect_rw(self.ws.domains_db)
        try:
            pack = self.registry.get(spec.domain)
            assert pack is not None
            result = self._dispatch(
                ledger,
                domains,
                pack,
                spec,
                change_request_id=change_request_id,
                actor=actor,
                actor_channel=actor_channel,
            )
            if owns_ledger:
                ledger.commit()
            if owns_domains:
                domains.commit()
            return result
        except Exception as exc:  # noqa: BLE001
            if owns_ledger:
                ledger.rollback()
            if owns_domains:
                domains.rollback()
            return ApplyResult(ok=False, operation=spec.operation, error=str(exc))
        finally:
            if owns_ledger:
                ledger.close()
            if owns_domains:
                domains.close()

    def validate(self, spec: OperationSpec) -> None:
        if not spec.domain:
            raise ValueError("operation missing domain")
        if spec.operation not in ALLOWED_OPS:
            raise ValueError(f"unsupported operation {spec.operation!r}")
        if not spec.object_type:
            raise ValueError("operation missing object_type")
        pack = self.registry.get(spec.domain)
        if pack is None:
            raise ValueError(f"no pack installed for domain {spec.domain!r}")
        if spec.object_type not in pack.objects:
            raise ValueError(
                f"object_type {spec.object_type!r} not in pack {spec.domain!r}"
            )
        allowed = pack.operations.get(spec.object_type) or []
        if spec.operation not in allowed:
            raise ValueError(
                f"operation {spec.operation!r} not allowed for "
                f"{spec.domain}.{spec.object_type}; allowed={allowed}"
            )
        if spec.operation in {"update", "correct", "delete"} and not spec.object_uid:
            raise ValueError(f"{spec.operation} requires object_uid")
        if spec.operation == "merge":
            if not spec.object_uid or not spec.merge_into_uid:
                raise ValueError("merge requires object_uid and merge_into_uid")

    def _dispatch(
        self,
        ledger: sqlite3.Connection,
        domains: sqlite3.Connection,
        pack: DomainPack,
        spec: OperationSpec,
        *,
        change_request_id: int | None,
        actor: str,
        actor_channel: str | None,
    ) -> ApplyResult:
        ts = now_iso()
        tname = table_name(pack.name, spec.object_type)
        obj = pack.objects[spec.object_type]

        if spec.operation == "create":
            return self._create(
                ledger, domains, pack, obj, tname, spec,
                change_request_id=change_request_id, actor=actor,
                actor_channel=actor_channel, now=ts,
            )
        if spec.operation in {"update", "correct"}:
            return self._update(
                ledger, domains, pack, obj, tname, spec,
                change_request_id=change_request_id, actor=actor,
                actor_channel=actor_channel, now=ts,
            )
        if spec.operation == "delete":
            return self._delete(
                ledger, domains, tname, spec,
                change_request_id=change_request_id, actor=actor,
                actor_channel=actor_channel, now=ts,
            )
        if spec.operation == "merge":
            return self._merge(
                ledger, domains, pack, obj, tname, spec,
                change_request_id=change_request_id, actor=actor,
                actor_channel=actor_channel, now=ts,
            )
        return ApplyResult(ok=False, error=f"unhandled op {spec.operation}")

    def _create(
        self,
        ledger: sqlite3.Connection,
        domains: sqlite3.Connection,
        pack: DomainPack,
        obj: ObjectSpec,
        tname: str,
        spec: OperationSpec,
        *,
        change_request_id: int | None,
        actor: str,
        actor_channel: str | None,
        now: str,
    ) -> ApplyResult:
        fields = self._normalize_fields(obj, spec.payload, span=str(spec.payload.get("_span") or ""))
        object_uid = spec.object_uid or canonical_uid(pack.name, spec.object_type)
        cols = ["object_uid", "entry_id", "created_at", "updated_at", "tombstoned"]
        vals: list[Any] = [object_uid, spec.entry_id, now, now, 0]
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
        title_field = obj.title_field
        natural_key = None
        if title_field and title_field in fields and fields[title_field]:
            natural_key = f"{pack.name}:{spec.object_type}:{fields[title_field]}"

        canonical = ensure_canonical_object(
            ledger,
            domain=pack.name,
            object_type=spec.object_type,
            store="domains",
            table_name=tname,
            row_id=row_id,
            natural_key=natural_key,
            now=now,
            uid=object_uid,
        )
        after = domains.execute(
            f"SELECT * FROM {tname} WHERE id = ?", (row_id,)
        ).fetchone()
        revision = write_object_revision(
            ledger,
            object_uid=canonical.uid,
            change_request_id=change_request_id,
            before_row=None,
            after_row=after,
            actor=actor,
            actor_channel=actor_channel,
            now=now,
            force_diff={k: {"from": None, "to": v} for k, v in fields.items()},
        )
        if spec.entry_id:
            insert_source_link(
                ledger,
                source_type="entry",
                source_id=spec.entry_id,
                target_uid=canonical.uid,
                relationship="created_from",
                now=now,
            )
        set_canonical_searchable_text(ledger, canonical.uid, fields, now=now)
        schedule_projection_stub(
            ledger,
            adapter="app_feed",
            object_key=f"{pack.name}:{spec.object_type}",
            change_request_id=change_request_id,
            now=now,
        )
        return ApplyResult(
            ok=True,
            object_uid=canonical.uid,
            row_id=row_id,
            revision=revision,
            created=True,
            operation="create",
            details={"fields": fields},
        )

    def _update(
        self,
        ledger: sqlite3.Connection,
        domains: sqlite3.Connection,
        pack: DomainPack,
        obj: ObjectSpec,
        tname: str,
        spec: OperationSpec,
        *,
        change_request_id: int | None,
        actor: str,
        actor_channel: str | None,
        now: str,
    ) -> ApplyResult:
        assert spec.object_uid
        before = domains.execute(
            f"SELECT * FROM {tname} WHERE object_uid = ? AND tombstoned = 0",
            (spec.object_uid,),
        ).fetchone()
        if before is None:
            return ApplyResult(
                ok=False, operation=spec.operation, error=f"object not found: {spec.object_uid}"
            )
        patch = {
            k: v
            for k, v in (spec.payload or {}).items()
            if k in obj.fields and _IDENT_RE.match(k)
        }
        if not patch:
            return ApplyResult(
                ok=True,
                object_uid=spec.object_uid,
                row_id=int(before["id"]),
                operation=spec.operation,
                details={"note": "no_field_changes"},
            )
        sets = ", ".join(f"{k} = ?" for k in patch)
        domains.execute(
            f"UPDATE {tname} SET {sets}, updated_at = ? WHERE object_uid = ?",
            [*patch.values(), now, spec.object_uid],
        )
        after = domains.execute(
            f"SELECT * FROM {tname} WHERE object_uid = ?", (spec.object_uid,)
        ).fetchone()
        ensure_canonical_object(
            ledger,
            domain=pack.name,
            object_type=spec.object_type,
            store="domains",
            table_name=tname,
            row_id=int(after["id"]),
            natural_key=None,
            now=now,
            uid=spec.object_uid,
        )
        revision = write_object_revision(
            ledger,
            object_uid=spec.object_uid,
            change_request_id=change_request_id,
            before_row=before,
            after_row=after,
            actor=actor,
            actor_channel=actor_channel,
            now=now,
        )
        after_fields = row_to_dict(after) or {}
        set_canonical_searchable_text(ledger, spec.object_uid, after_fields, now=now)
        schedule_projection_stub(
            ledger,
            adapter="app_feed",
            object_key=f"{pack.name}:{spec.object_type}",
            change_request_id=change_request_id,
            now=now,
        )
        return ApplyResult(
            ok=True,
            object_uid=spec.object_uid,
            row_id=int(after["id"]),
            revision=revision,
            operation=spec.operation,
            details={"fields": patch},
        )

    def _delete(
        self,
        ledger: sqlite3.Connection,
        domains: sqlite3.Connection,
        tname: str,
        spec: OperationSpec,
        *,
        change_request_id: int | None,
        actor: str,
        actor_channel: str | None,
        now: str,
    ) -> ApplyResult:
        assert spec.object_uid
        before = domains.execute(
            f"SELECT * FROM {tname} WHERE object_uid = ?", (spec.object_uid,)
        ).fetchone()
        if before is None:
            return ApplyResult(
                ok=False, operation="delete", error=f"object not found: {spec.object_uid}"
            )
        domains.execute(
            f"UPDATE {tname} SET tombstoned = 1, updated_at = ? WHERE object_uid = ?",
            (now, spec.object_uid),
        )
        ledger.execute(
            """
            UPDATE canonical_object
            SET status = 'tombstoned', updated_at = ?
            WHERE uid = ?
            """,
            (now, spec.object_uid),
        )
        after = domains.execute(
            f"SELECT * FROM {tname} WHERE object_uid = ?", (spec.object_uid,)
        ).fetchone()
        revision = write_object_revision(
            ledger,
            object_uid=spec.object_uid,
            change_request_id=change_request_id,
            before_row=before,
            after_row=after,
            actor=actor,
            actor_channel=actor_channel,
            now=now,
            force_diff={"tombstoned": {"from": 0, "to": 1}, "status": {"from": "active", "to": "tombstoned"}},
        )
        schedule_projection_stub(
            ledger,
            adapter="app_feed",
            object_key=f"{spec.domain}:{spec.object_type}",
            change_request_id=change_request_id,
            now=now,
        )
        return ApplyResult(
            ok=True,
            object_uid=spec.object_uid,
            row_id=int(before["id"]),
            revision=revision,
            operation="delete",
        )

    def _merge(
        self,
        ledger: sqlite3.Connection,
        domains: sqlite3.Connection,
        pack: DomainPack,
        obj: ObjectSpec,
        tname: str,
        spec: OperationSpec,
        *,
        change_request_id: int | None,
        actor: str,
        actor_channel: str | None,
        now: str,
    ) -> ApplyResult:
        """Merge object_uid into merge_into_uid; tombstone the source."""
        assert spec.object_uid and spec.merge_into_uid
        if spec.object_uid == spec.merge_into_uid:
            return ApplyResult(ok=False, operation="merge", error="cannot merge object into itself")

        source = domains.execute(
            f"SELECT * FROM {tname} WHERE object_uid = ? AND tombstoned = 0",
            (spec.object_uid,),
        ).fetchone()
        survivor = domains.execute(
            f"SELECT * FROM {tname} WHERE object_uid = ? AND tombstoned = 0",
            (spec.merge_into_uid,),
        ).fetchone()
        if source is None or survivor is None:
            return ApplyResult(ok=False, operation="merge", error="merge source or survivor missing")

        # Integrity: both must be active canonical objects
        for uid in (spec.object_uid, spec.merge_into_uid):
            row = ledger.execute(
                "SELECT status FROM canonical_object WHERE uid = ?", (uid,)
            ).fetchone()
            if row is None or row["status"] != "active":
                return ApplyResult(
                    ok=False,
                    operation="merge",
                    error=f"canonical integrity failed for {uid}",
                )

        # Optional field overlay from payload onto survivor
        patch = {
            k: v
            for k, v in (spec.payload or {}).items()
            if k in obj.fields and _IDENT_RE.match(k)
        }
        if patch:
            sets = ", ".join(f"{k} = ?" for k in patch)
            domains.execute(
                f"UPDATE {tname} SET {sets}, updated_at = ? WHERE object_uid = ?",
                [*patch.values(), now, spec.merge_into_uid],
            )

        domains.execute(
            f"UPDATE {tname} SET tombstoned = 1, updated_at = ? WHERE object_uid = ?",
            (now, spec.object_uid),
        )
        ledger.execute(
            """
            UPDATE canonical_object
            SET status = 'merged', merged_into_uid = ?, updated_at = ?
            WHERE uid = ?
            """,
            (spec.merge_into_uid, now, spec.object_uid),
        )
        ledger.execute(
            "UPDATE canonical_object SET updated_at = ? WHERE uid = ?",
            (now, spec.merge_into_uid),
        )
        after_survivor = domains.execute(
            f"SELECT * FROM {tname} WHERE object_uid = ?", (spec.merge_into_uid,)
        ).fetchone()
        revision = write_object_revision(
            ledger,
            object_uid=spec.merge_into_uid,
            change_request_id=change_request_id,
            before_row=survivor,
            after_row=after_survivor,
            actor=actor,
            actor_channel=actor_channel,
            now=now,
            force_diff={
                **{k: {"from": survivor[k] if k in survivor.keys() else None, "to": v} for k, v in patch.items()},
                "_merged_from": {"from": None, "to": spec.object_uid},
            },
        )
        write_object_revision(
            ledger,
            object_uid=spec.object_uid,
            change_request_id=change_request_id,
            before_row=source,
            after_row=None,
            actor=actor,
            actor_channel=actor_channel,
            now=now,
            force_diff={
                "status": {"from": "active", "to": "merged"},
                "merged_into_uid": {"from": None, "to": spec.merge_into_uid},
            },
        )
        # FK/orphan check: source must still reference survivor
        orphan = ledger.execute(
            """
            SELECT uid FROM canonical_object
            WHERE uid = ? AND (merged_into_uid IS NULL OR merged_into_uid != ?)
            """,
            (spec.object_uid, spec.merge_into_uid),
        ).fetchone()
        if orphan:
            return ApplyResult(ok=False, operation="merge", error="merge left orphan link")

        schedule_projection_stub(
            ledger,
            adapter="app_feed",
            object_key=f"{pack.name}:{spec.object_type}",
            change_request_id=change_request_id,
            now=now,
        )
        return ApplyResult(
            ok=True,
            object_uid=spec.merge_into_uid,
            row_id=int(survivor["id"]),
            revision=revision,
            operation="merge",
            details={
                "merged_uid": spec.object_uid,
                "survivor_uid": spec.merge_into_uid,
            },
        )

    def _normalize_fields(
        self, obj: ObjectSpec, payload: dict[str, Any], *, span: str
    ) -> dict[str, Any]:
        raw = dict(payload or {})
        raw.pop("_span", None)
        raw.pop("links", None)
        raw.pop("disposition", None)
        out: dict[str, Any] = {}
        for fname, fspec in obj.fields.items():
            if fname in raw and raw[fname] is not None:
                coerced = _coerce(fspec, raw[fname])
                if isinstance(coerced, _Uncoercible):
                    logger.warning("dropping field %s: %s", fname, coerced.reason)
                    continue
                out[fname] = coerced
            elif fspec.default == "capture_time":
                out[fname] = now_iso()
            elif fspec.default is not None:
                out[fname] = fspec.default
            elif fspec.required and obj.title_field == fname and span:
                out[fname] = span[:120]
            elif fspec.required and fspec.type in {"text", "enum"} and span:
                # last-resort fill for required text so never-drop create can land
                if fname == obj.title_field:
                    out[fname] = span[:120]
        # Include optional provided fields even if not in loop... already covered
        for fname, value in raw.items():
            if fname in obj.fields and fname not in out and value is not None:
                coerced = _coerce(obj.fields[fname], value)
                if not isinstance(coerced, _Uncoercible):
                    out[fname] = coerced
        return out


class _Uncoercible:
    """Sentinel: the model gave a value this field's type cannot hold."""

    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        self.reason = reason


def _coerce(fspec: FieldSpec, value: Any) -> Any:
    if fspec.type in {"number", "integer"}:
        try:
            return float(value) if fspec.type == "number" else int(value)
        except (TypeError, ValueError):
            # Free text routinely carries things like "2:1:1" or "a dozen" into
            # a numeric field. Dropping one field beats failing the whole
            # change request and stranding the note (product promise 2).
            return _Uncoercible(f"{value!r} is not a {fspec.type}")
    if fspec.type == "boolean":
        if isinstance(value, bool):
            return int(value)
        return int(bool(value))
    if fspec.type == "datetime" and isinstance(value, str):
        # Models echo the schema's own default token back as a literal; it must
        # never land in a datetime column.
        if value.strip() in _DEFAULT_TOKENS:
            return now_iso()
    if fspec.type == "attachment" and fspec.many and not isinstance(value, str):
        return json.dumps(value)
    return value


def load_domain_row(
    domains_db: Path, domain: str, object_type: str, object_uid: str
) -> dict[str, Any] | None:
    tname = table_name(domain, object_type)
    conn = connect_rw(domains_db)
    try:
        row = conn.execute(
            f"SELECT * FROM {tname} WHERE object_uid = ?", (object_uid,)
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()
