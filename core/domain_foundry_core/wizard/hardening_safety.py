"""Recoverable snapshots for schema hardening changes."""

from __future__ import annotations

import base64
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from domain_foundry_core.clock import now
from domain_foundry_core.packs.models import DomainPack
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.packs.schema_compiler import table_name
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro, connect_rw


def create_snapshot(workspace: Workspace, pack: DomainPack, object_type: str) -> dict[str, Any]:
    """Copy the pack and the affected table before a migration can write."""
    pack_root = pack.root.resolve()
    packs_root = workspace.packs_dir.resolve()
    if not pack_root.is_relative_to(packs_root):
        raise ValueError("hardening is only supported for workspace-installed packs")

    table = table_name(pack.name, object_type)
    backup_root = workspace.home / "backups" / "hardening"
    current = _now_utc()
    stamp = current.strftime("%Y%m%dT%H%M%S%fZ")
    snapshot_root = backup_root / f"{stamp}-{pack.name}"
    suffix = 0
    while snapshot_root.exists():
        suffix += 1
        snapshot_root = backup_root / f"{stamp}-{pack.name}-{suffix}"
    snapshot_root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(pack_root, snapshot_root / "pack")
    _backup_table(workspace, table, snapshot_root / "domains-table.json")
    manifest = {
        "domain": pack.name,
        "object_type": object_type,
        "table": table,
        "pack_root": str(pack_root),
        "pack_backup": "pack",
        "table_backup": "domains-table.json",
        "created_at": _iso_seconds(current),
    }
    (snapshot_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"path": str(snapshot_root), **manifest}


def restore_latest_snapshot(
    workspace: Workspace, domain: str, *, registry: PackRegistry | None = None
) -> dict[str, Any]:
    """Restore the newest snapshot for a domain without touching other tables."""
    root = workspace.home / "backups" / "hardening"
    candidates: list[tuple[Path, dict[str, Any]]] = []
    if root.is_dir():
        for path in root.iterdir():
            manifest_path = path / "manifest.json"
            if not path.is_dir() or not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(manifest, dict) and manifest.get("domain") == domain:
                candidates.append((path, manifest))
    if not candidates:
        raise ValueError(f"no hardening snapshot exists for domain {domain!r}")
    snapshot_root, manifest = max(candidates, key=lambda item: (item[0].stat().st_mtime, item[0].name))

    current = registry.get(domain) if registry is not None else None
    pack_root = (
        current.root.resolve()
        if current is not None
        else (workspace.packs_dir / domain).resolve()
    )
    if not pack_root.is_relative_to(workspace.packs_dir.resolve()):
        raise ValueError("hardening rollback is only supported for workspace-installed packs")
    pack_backup = snapshot_root / "pack"
    if not pack_backup.is_dir():
        raise ValueError("hardening snapshot is missing its pack copy")
    if not pack_backup.resolve().is_relative_to(snapshot_root.resolve()):
        raise ValueError("hardening snapshot pack copy is outside the snapshot")
    object_type = str(manifest.get("object_type") or "")
    expected_table = table_name(domain, object_type)
    if manifest.get("table") != expected_table:
        raise ValueError("hardening snapshot table does not match its domain")
    table_backup = snapshot_root / "domains-table.json"
    if not table_backup.is_file() or not table_backup.resolve().is_relative_to(snapshot_root.resolve()):
        raise ValueError("hardening snapshot is missing its table backup")
    shutil.rmtree(pack_root)
    shutil.copytree(pack_backup, pack_root)
    _restore_table(workspace, expected_table, table_backup)
    return {
        "rolled_back": True,
        "domain": domain,
        "snapshot": str(snapshot_root),
        "table": manifest["table"],
        "pack_path": str(pack_root),
        "restored_at": _iso_seconds(_now_utc()),
    }


def _now_utc() -> datetime:
    current = now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def _iso_seconds(current: datetime) -> str:
    return current.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _backup_table(workspace: Workspace, table: str, path: Path) -> None:
    conn = connect_ro(workspace.domains_db)
    try:
        table_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if table_row is None or not table_row["sql"]:
            raise ValueError(f"affected table is missing: {table}")
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        rows = [
            [_encode(row[column]) for column in columns]
            for row in conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY id")
        ]
        indexes = [
            row["sql"]
            for row in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? "
                "AND sql IS NOT NULL ORDER BY name",
                (table,),
            )
        ]
        sequence_row = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)
        ).fetchone()
    finally:
        conn.close()
    path.write_text(
        json.dumps(
            {
                "table_sql": table_row["sql"],
                "columns": columns,
                "rows": rows,
                "indexes": indexes,
                "sequence": sequence_row["seq"] if sequence_row else None,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _restore_table(workspace: Workspace, table: str, path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    columns = [str(column) for column in payload["columns"]]
    if not columns or not isinstance(payload.get("table_sql"), str):
        raise ValueError("hardening snapshot table backup is invalid")
    conn = connect_rw(workspace.domains_db)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        quoted_table = _quote_identifier(table)
        conn.execute(f"DROP TABLE IF EXISTS {quoted_table}")
        conn.execute(payload["table_sql"])
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(_quote_identifier(column) for column in columns)
        for row in payload.get("rows") or []:
            conn.execute(
                f"INSERT INTO {quoted_table} ({column_sql}) VALUES ({placeholders})",
                [_decode(value) for value in row],
            )
        for statement in payload.get("indexes") or []:
            conn.execute(statement)
        sequence = payload.get("sequence")
        if sequence is not None:
            updated = conn.execute(
                "UPDATE sqlite_sequence SET seq = ? WHERE name = ?",
                (int(sequence), table),
            )
            if updated.rowcount == 0:
                conn.execute(
                    "INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)",
                    (table, int(sequence)),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _quote_identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("invalid SQLite identifier in hardening snapshot")
    return '"' + value.replace('"', '""') + '"'


def _encode(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__bytes__"}:
        return base64.b64decode(value["__bytes__"])
    return value
