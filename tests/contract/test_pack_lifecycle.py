"""Filesystem-backed pack lifecycle receipts and cleanup guarantees."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import domain_foundry_core.packs.registry as registry_module
from domain_foundry_core.api.app import create_app
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace

REPO = Path(__file__).resolve().parents[2]
COFFEE = REPO / "examples" / "heldout" / "packs" / "coffee"


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_external_pack_lifecycle_rolls_back_byte_exactly_and_uninstalls(
    workspace: Workspace, tmp_path: Path
):
    source = tmp_path / "coffee"
    shutil.copytree(COFFEE, source)
    registry = PackRegistry(workspace)

    preview = registry.preview(source)
    assert preview["valid"] is True
    assert preview["declared_permissions"] == []
    assert "data:own_tables" in preview["effective_permissions"]
    assert "its own domain tables" in preview["touches"]
    assert "pack.yaml" in preview["files"]

    installed = registry.install(source)
    assert installed["status"] == "installed"
    installed_root = workspace.packs_dir / "coffee"
    before_upgrade = _tree_digest(installed_root)

    pack_yaml = source / "pack.yaml"
    pack_yaml.write_text(
        pack_yaml.read_text(encoding="utf-8").replace("version: 0.1.0", "version: 0.2.0"),
        encoding="utf-8",
    )
    upgraded = registry.upgrade(source)
    assert upgraded["status"] == "upgraded"
    assert upgraded["backup"]

    rolled_back = registry.rollback("coffee", Path(upgraded["backup"]))
    assert rolled_back["status"] == "rolled_back"
    assert _tree_digest(installed_root) == before_upgrade

    exported = registry.export("coffee", tmp_path / "exported-coffee")
    assert exported["status"] == "exported"
    assert (tmp_path / "exported-coffee" / "pack.yaml").is_file()

    with sqlite3.connect(workspace.ledger_db) as connection:
        connection.execute(
            """
            INSERT INTO projection_outbox
                (adapter, object_key, reason, status, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            ("markdown", "coffee:brew", "lifecycle test", "now", "now"),
        )
        connection.execute(
            """
            INSERT INTO projection_watermark (adapter, object_key, watermark, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            ("markdown", "coffee:brew", "1", "now"),
        )
        connection.commit()

    removed = registry.uninstall("coffee")
    assert removed["status"] == "uninstalled"
    assert not installed_root.exists()
    with sqlite3.connect(workspace.domains_db) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("coffee__brew",),
        ).fetchone()
    assert table is None
    with sqlite3.connect(workspace.ledger_db) as connection:
        projections = connection.execute(
            "SELECT COUNT(*) FROM projection_outbox WHERE object_key LIKE 'coffee:%'"
        ).fetchone()
        watermarks = connection.execute(
            "SELECT COUNT(*) FROM projection_watermark WHERE object_key LIKE 'coffee:%'"
        ).fetchone()
    assert projections == (0,)
    assert watermarks == (0,)


def test_pack_lifecycle_rejects_source_symlinks(workspace: Workspace, tmp_path: Path):
    source = tmp_path / "coffee"
    shutil.copytree(COFFEE, source)
    outside = tmp_path / "outside.txt"
    outside.write_text("not pack data", encoding="utf-8")
    os.symlink(outside, source / "unexpected-link")

    registry = PackRegistry(workspace)
    with pytest.raises(ValueError, match="symlink"):
        registry.preview(source)


def test_pack_lifecycle_http_is_authenticated_and_uses_explicit_operations(
    tmp_path: Path,
):
    source = tmp_path / "coffee"
    shutil.copytree(COFFEE, source)
    home = tmp_path / "home"
    client = TestClient(create_app(home, api_token="test-token", enable_drain_loop=False))
    headers = {"Authorization": "Bearer test-token"}

    unauthenticated = client.post("/api/packs/preview", json={"source": str(source)})
    assert unauthenticated.status_code == 401

    preview = client.post("/api/packs/preview", json={"source": str(source)}, headers=headers)
    assert preview.status_code == 200
    assert preview.json()["declared_permissions"] == []

    installed = client.post("/api/packs/install", json={"source": str(source)}, headers=headers)
    assert installed.status_code == 200
    assert installed.json()["status"] == "installed"

    inspected = client.post("/api/packs/inspect", json={"source": "coffee"}, headers=headers)
    assert inspected.status_code == 200
    assert inspected.json()["installed"] is True

    activated = client.post("/api/packs/activate", json={"name": "coffee"}, headers=headers)
    assert activated.status_code == 200
    assert activated.json()["status"] == "activated"

    destination = tmp_path / "exported"
    exported = client.post(
        "/api/packs/export",
        json={"name": "coffee", "destination": str(destination)},
        headers=headers,
    )
    assert exported.status_code == 200
    assert destination.joinpath("pack.yaml").is_file()

    removed = client.post("/api/packs/uninstall", json={"name": "coffee"}, headers=headers)
    assert removed.status_code == 200
    assert removed.json()["status"] == "uninstalled"


def test_registry_reads_do_not_observe_a_partial_reload(
    workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "coffee"
    shutil.copytree(COFFEE, source)
    registry = PackRegistry(workspace)
    registry.install(source)

    original_load = registry_module.load_pack
    started = threading.Event()

    def slow_load(root: Path, *, validate: bool = True):
        started.set()
        time.sleep(0.02)
        return original_load(root, validate=validate)

    monkeypatch.setattr(registry_module, "load_pack", slow_load)
    worker = threading.Thread(target=registry.reload)
    worker.start()
    assert started.wait(timeout=1)
    assert registry.get("coffee") is not None
    worker.join(timeout=1)
    assert not worker.is_alive()
