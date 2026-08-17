"""Snapshot, rollback, and authenticated hardening endpoint contracts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.packs.schema_compiler import table_name
from domain_foundry_core.security.store import connect_ro

TOKEN = "hardening-secret"


def _table_snapshot(path: Path, table: str) -> tuple[bytes, list[tuple[object, ...]]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()[0]
        columns = [row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        rows = [tuple(row[column] for column in columns) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY id')]
        payload = json.dumps(
            {"sql": sql, "columns": columns, "rows": rows},
            sort_keys=True,
            default=str,
        ).encode()
        return hashlib.sha256(payload).digest(), rows
    finally:
        conn.close()


def test_hardening_http_apply_snapshot_rollback_restores_bytes_and_auth(tmp_path: Path):
    home = tmp_path / "home"
    api = HarnessAPI(home)
    api.init()
    api.packs.activate_bundled("sourdough")
    created = api.apply_operation(
        domain="sourdough",
        operation="create",
        object_type="bake",
        fields={
            "loaf_name": "Rollback loaf",
            "hydration": 76,
            "result": "great",
            "notes": "keep this row",
        },
    )
    assert created["ok"] is True
    table = table_name("sourdough", "bake")
    before_pack = {
        name: (api.packs.get("sourdough").root / name).read_bytes()  # type: ignore[union-attr]
        for name in ("pack.yaml", "schema.yaml", "routing.yaml")
    }
    before_table, before_rows = _table_snapshot(api.workspace.domains_db, table)

    client = TestClient(create_app(home, api_token=TOKEN, enable_drain_loop=False))
    unauthenticated = client.post(
        "/api/domains/sourdough/rollback", headers={}
    )
    assert unauthenticated.status_code == 401

    preview = client.post(
        "/api/domains/sourdough/hardening/preview",
        json={"text": "add a crumb_photo field"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert preview.status_code == 200
    assert preview.json()["plan"]["added"][0]["name"] == "crumb_photo"

    applied = client.post(
        "/api/domains/sourdough/hardening/apply",
        json={"text": "add a crumb_photo field"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert applied.status_code == 200
    applied_payload = applied.json()
    assert applied_payload["applied"] is True
    snapshot = Path(applied_payload["snapshot"]["path"])
    assert snapshot.is_dir()
    assert (snapshot / "pack" / "pack.yaml").is_file()
    assert (snapshot / "domains-table.json").is_file()
    assert "crumb_photo:" not in before_pack["schema.yaml"].decode()

    rollback = client.post(
        "/api/domains/sourdough/rollback",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert rollback.status_code == 200
    assert rollback.json()["rolled_back"] is True

    api.packs.reload()
    restored_pack = api.packs.get("sourdough")
    assert restored_pack is not None
    for name, content in before_pack.items():
        assert (restored_pack.root / name).read_bytes() == content
    after_table, after_rows = _table_snapshot(api.workspace.domains_db, table)
    assert after_table == before_table
    assert after_rows == before_rows
    assert "crumb_photo" not in restored_pack.objects["bake"].fields

    conn = connect_ro(api.workspace.ledger_db)
    try:
        active = conn.execute(
            "SELECT field_contract_json FROM schema_registry "
            "WHERE domain = 'sourdough' AND object_type = 'bake' AND active = 1"
        ).fetchone()
    finally:
        conn.close()
    assert active is not None
    assert '"crumb_photo"' not in active["field_contract_json"]
