"""Canonical object UIDs + append-only revision journal."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from domain_foundry_core.ids import canonical_uid

IGNORED_REVISION_FIELDS = {"id", "created_at", "updated_at", "object_uid", "entry_id"}


@dataclass(frozen=True)
class CanonicalObjectRef:
    uid: str
    created: bool
    natural_key: str | None


def row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}


def changed_fields(before_row: Any, after_row: Any) -> dict[str, dict[str, Any]]:
    before = row_to_dict(before_row) or {}
    after = row_to_dict(after_row) or {}
    keys = sorted((set(before) | set(after)) - IGNORED_REVISION_FIELDS)
    diff: dict[str, dict[str, Any]] = {}
    for key in keys:
        before_value = before.get(key)
        after_value = after.get(key)
        if before_value != after_value:
            diff[key] = {"from": before_value, "to": after_value}
    return diff


def schema_version(ledger_conn, domain: str, object_type: str) -> int:
    row = ledger_conn.execute(
        """
        SELECT COALESCE(MAX(schema_version), 1) AS version
        FROM schema_registry
        WHERE domain = ? AND object_type = ? AND active = 1
        """,
        (domain, object_type),
    ).fetchone()
    return int(row["version"]) if row and row["version"] is not None else 1


def ensure_canonical_object(
    ledger_conn,
    *,
    domain: str,
    object_type: str,
    store: str,
    table_name: str,
    row_id: int,
    natural_key: str | None,
    now: str,
    uid: str | None = None,
) -> CanonicalObjectRef:
    existing = ledger_conn.execute(
        """
        SELECT uid, natural_key
        FROM canonical_object
        WHERE store = ? AND table_name = ? AND row_id = ?
        """,
        (store, table_name, int(row_id)),
    ).fetchone()
    if existing:
        safe_nk = natural_key
        if natural_key:
            conflict = ledger_conn.execute(
                """
                SELECT uid FROM canonical_object
                WHERE domain = ? AND object_type = ? AND natural_key = ? AND uid != ?
                """,
                (domain, object_type, natural_key, existing["uid"]),
            ).fetchone()
            if conflict:
                safe_nk = None
        ledger_conn.execute(
            """
            UPDATE canonical_object
            SET natural_key = COALESCE(natural_key, ?),
                schema_version = ?,
                updated_at = ?,
                status = CASE WHEN status = 'tombstoned' THEN status ELSE 'active' END
            WHERE uid = ?
            """,
            (safe_nk, schema_version(ledger_conn, domain, object_type), now, existing["uid"]),
        )
        return CanonicalObjectRef(
            uid=str(existing["uid"]),
            created=False,
            natural_key=safe_nk or existing["natural_key"],
        )

    if natural_key:
        collision = ledger_conn.execute(
            """
            SELECT uid, row_id FROM canonical_object
            WHERE domain = ? AND object_type = ? AND natural_key = ?
            """,
            (domain, object_type, natural_key),
        ).fetchone()
        if collision and collision["row_id"] in (None, int(row_id)):
            ledger_conn.execute(
                """
                UPDATE canonical_object
                SET store = ?, table_name = ?, row_id = ?, schema_version = ?, updated_at = ?
                WHERE uid = ?
                """,
                (
                    store,
                    table_name,
                    int(row_id),
                    schema_version(ledger_conn, domain, object_type),
                    now,
                    collision["uid"],
                ),
            )
            return CanonicalObjectRef(
                uid=str(collision["uid"]), created=False, natural_key=natural_key
            )
        if collision:
            natural_key = None

    object_uid = uid or canonical_uid(domain, object_type)
    ledger_conn.execute(
        """
        INSERT INTO canonical_object (
            uid, domain, object_type, store, table_name, row_id,
            natural_key, status, schema_version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (
            object_uid,
            domain,
            object_type,
            store,
            table_name,
            int(row_id),
            natural_key,
            schema_version(ledger_conn, domain, object_type),
            now,
            now,
        ),
    )
    return CanonicalObjectRef(uid=object_uid, created=True, natural_key=natural_key)


def write_object_revision(
    ledger_conn,
    *,
    object_uid: str,
    change_request_id: int | None,
    before_row: Any,
    after_row: Any,
    actor: str,
    actor_channel: str | None,
    now: str,
    force_diff: dict[str, dict[str, Any]] | None = None,
) -> int | None:
    diff = force_diff if force_diff is not None else changed_fields(before_row, after_row)
    if not diff:
        return None
    row = ledger_conn.execute(
        "SELECT COALESCE(MAX(revision), 0) + 1 AS next_revision "
        "FROM object_revision WHERE object_uid = ?",
        (object_uid,),
    ).fetchone()
    revision = int(row["next_revision"]) if row else 1
    ledger_conn.execute(
        """
        INSERT INTO object_revision (
            object_uid, change_request_id, revision, changed_fields_json,
            actor, actor_channel, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            object_uid,
            change_request_id,
            revision,
            json.dumps(diff, sort_keys=True),
            actor,
            actor_channel,
            now,
        ),
    )
    ledger_conn.execute(
        "UPDATE canonical_object SET updated_at = ? WHERE uid = ?",
        (now, object_uid),
    )
    return revision


def write_change_request_result(
    ledger_conn,
    *,
    change_request_id: int,
    object_uid: str | None,
    result_json: dict[str, Any] | None,
    error: str | None,
    now: str,
    status: str = "applied",
) -> None:
    ledger_conn.execute(
        """
        UPDATE change_request
        SET object_uid = COALESCE(?, object_uid),
            result_json = ?,
            error = ?,
            status = ?,
            applied_at = CASE WHEN ? IS NOT NULL THEN applied_at ELSE COALESCE(applied_at, ?) END
        WHERE id = ?
        """,
        (
            object_uid,
            json.dumps(result_json, sort_keys=True) if result_json is not None else None,
            error,
            status if error is None else "failed",
            error,
            now,
            change_request_id,
        ),
    )


def insert_source_link(
    ledger_conn,
    *,
    source_type: str,
    source_id: str,
    target_uid: str,
    relationship: str,
    confidence: float = 1.0,
    now: str,
) -> None:
    ledger_conn.execute(
        """
        INSERT OR IGNORE INTO source_link
            (source_type, source_id, target_type, target_id, relationship, confidence, created_at)
        VALUES (?, ?, 'canonical_object', ?, ?, ?, ?)
        """,
        (source_type, source_id, target_uid, relationship, float(confidence), now),
    )


def schedule_projection_stub(
    ledger_conn,
    *,
    adapter: str | None = None,
    object_key: str,
    change_request_id: int | None,
    now: str,
    reason: str = "canonical_apply",
) -> None:
    """Fan a canonical commit out to every projection adapter (invariant 11).

    The `adapter` argument is retained for call-site compatibility but ignored:
    the ProjectionCoordinator owns the adapter set (app_feed + markdown).
    """
    from domain_foundry_core.projections.coordinator import schedule_projections

    schedule_projections(
        ledger_conn,
        object_key=object_key,
        change_request_id=change_request_id,
        now=now,
        reason=reason,
    )
