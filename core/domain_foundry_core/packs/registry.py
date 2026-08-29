"""Installed pack registry and safe pack lifecycle."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from domain_foundry_core.clock import now
from domain_foundry_core.ledger.migrate import ensure_migrated
from domain_foundry_core.packs.loader import (
    bundled_packs_root,
    discover_entry_point_packs,
    discover_pack_dirs,
    install_pack,
    load_pack,
)
from domain_foundry_core.packs.models import DomainPack
from domain_foundry_core.packs.schema_compiler import (
    apply_pack_schema,
    table_name,
    uninstall_blockers,
    write_migration,
)
from domain_foundry_core.paths import Workspace, overlay_pack_dirs
from domain_foundry_core.security.store import connect_rw


class PackRegistry:
    def __init__(self, workspace: Workspace | None = None) -> None:
        self.ws = workspace or Workspace()
        self.ws.ensure_layout()
        ensure_migrated(self.ws.ledger_db, "ledger")
        ensure_migrated(self.ws.domains_db, "domains")
        self._lock = threading.RLock()
        self._packs: dict[str, DomainPack] = {}
        self.reload()

    @property
    def _metadata_path(self) -> Path:
        return self.ws.home / "pack_registry.json"

    @property
    def _backup_dir(self) -> Path:
        return self.ws.home / "backups" / "packs"

    def _metadata(self) -> dict[str, Any]:
        if not self._metadata_path.exists():
            return {"packs": {}}
        try:
            raw = json.loads(self._metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {"packs": {}}
        return raw if isinstance(raw, dict) and isinstance(raw.get("packs"), dict) else {"packs": {}}

    def _save_metadata(self, metadata: dict[str, Any]) -> None:
        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="pack-registry-", dir=self._metadata_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self._metadata_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @staticmethod
    def _effective_permissions(pack: DomainPack) -> list[str]:
        """Normalize legacy packs into the permissions users actually preview."""
        permissions = set(pack.manifest.permissions)
        if pack.objects:
            permissions.add("data:own_tables")
        if pack.projections.app:
            permissions.add("projection:app")
        if pack.projections.markdown:
            permissions.add("projection:markdown")
        permissions.update(f"capability:{name}" for name in pack.capabilities)
        return sorted(permissions)

    @staticmethod
    def _summary(pack: DomainPack) -> dict[str, Any]:
        return {
            "name": pack.name,
            "version": pack.version,
            "title": pack.manifest.title,
            "description": pack.manifest.description,
            "permissions": list(pack.manifest.permissions),
            "effective_permissions": PackRegistry._effective_permissions(pack),
            "objects": sorted(pack.objects),
            "capabilities": sorted(pack.capabilities),
            "path": str(pack.root),
        }

    @staticmethod
    def _safe_source(source: Path) -> Path:
        path = Path(source).expanduser()
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"pack source is not a directory: {path}")
        if path.is_symlink():
            raise ValueError("pack source symlink is not allowed")
        resolved = path.resolve()
        for child in resolved.rglob("*"):
            if child.is_symlink():
                raise ValueError(f"pack contains symlink: {child.relative_to(resolved)}")
        return resolved

    def _record(self, pack: DomainPack, *, active: bool = True, backup: Path | None = None) -> None:
        metadata = self._metadata()
        row = metadata["packs"].setdefault(pack.name, {})
        row.update(
            {
                "name": pack.name,
                "version": pack.version,
                "path": str(pack.root),
                "active": active,
                "updated_at": now().timestamp(),
            }
        )
        if backup is not None:
            row.setdefault("backups", []).append(str(backup))
        self._save_metadata(metadata)

    def _snapshot(self, name: str) -> Path:
        source = self.ws.packs_dir / name
        try:
            source = self._safe_source(source)
        except (FileNotFoundError, ValueError) as exc:
            raise FileNotFoundError(f"installed pack not found: {name}") from exc
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        destination = self._backup_dir / f"{name}-{secrets.token_hex(8)}"
        shutil.copytree(source, destination, symlinks=False)
        return destination

    def _workspace_pack_root(self, pack: DomainPack) -> Path:
        """Return the workspace-owned root, rejecting overlay-only packs."""
        expected = (self.ws.packs_dir / pack.name).resolve()
        if pack.root.resolve() != expected:
            raise ValueError(f"pack is not installed in this workspace: {pack.name}")
        return expected

    def search_paths(self) -> list[Path]:
        """Active pack roots: workspace install dir + private overlay dirs.

        Bundled packs remain a catalog only (see bundled_catalog /
        activate_bundled) — not auto-enabled. Overlay dirs come from
        ``DOMAIN_FOUNDRY_PACKS_PATH`` so personal packs can live outside the
        OSS checkout (e.g. ``~/HermesWorkspace/packs``).
        """
        return [self.ws.packs_dir, *overlay_pack_dirs()]

    def bundled_catalog(self) -> list[Path]:
        return discover_pack_dirs([bundled_packs_root()])

    def reload(self) -> None:
        with self._lock:
            # Order: workspace → pip entry points → DOMAIN_FOUNDRY_PACKS_PATH
            # overlay. Later sources win on name collision so a private overlay
            # pack can shadow a same-named install or entry-point pack.
            dirs = (
                discover_pack_dirs([self.ws.packs_dir])
                + discover_entry_point_packs()
                + discover_pack_dirs(overlay_pack_dirs())
            )
            loaded: dict[str, DomainPack] = {}
            for d in dirs:
                try:
                    pack = load_pack(d, validate=True)
                except Exception:
                    continue
                loaded[pack.name] = pack
            # Swap only after the complete scan. Readers either see the previous
            # coherent catalog or the new one, never the transient empty map.
            self._packs = loaded

    def list(self) -> list[DomainPack]:
        with self._lock:
            return sorted(self._packs.values(), key=lambda p: p.name)

    def get(self, name: str) -> DomainPack | None:
        with self._lock:
            return self._packs.get(name)

    def get_by_alias(self, name_or_alias: str) -> DomainPack | None:
        with self._lock:
            if name_or_alias in self._packs:
                return self._packs[name_or_alias]
            for pack in self._packs.values():
                if name_or_alias in pack.manifest.aliases:
                    return pack
            return None

    def validate(self, name: str | None = None) -> list[str]:
        """Return list of error strings (empty = ok)."""
        with self._lock:
            targets = [self._packs[name]] if name and name in self._packs else list(self._packs.values())
        errors: list[str] = []
        for pack in targets:
            try:
                load_pack(pack.root, validate=True)
            except Exception as exc:
                errors.append(f"{pack.name}: {exc}")
        return errors

    def inspect(self, name_or_source: str | Path) -> dict[str, Any]:
        """Return a user-readable, side-effect-free pack inspection."""
        source = Path(name_or_source) if isinstance(name_or_source, Path) else None
        if source is not None or "/" in str(name_or_source):
            root = self._safe_source(source or Path(str(name_or_source)))
            pack = load_pack(root, validate=True)
        else:
            pack = self.get_by_alias(str(name_or_source))
            if pack is None:
                raise KeyError(f"unknown pack: {name_or_source}")
        result = self._summary(pack)
        result["valid"] = True
        result["installed"] = (self.ws.packs_dir / pack.name).is_dir()
        return result

    def preview(self, source: Path) -> dict[str, Any]:
        """Validate a pack and show its declared permissions before install."""
        root = self._safe_source(source)
        pack = load_pack(root, validate=True)
        result = self._summary(pack)
        result.update(
            {
                "valid": True,
                "installed": (self.ws.packs_dir / pack.name).is_dir(),
                "would_replace": (self.ws.packs_dir / pack.name).is_dir(),
                "declared_permissions": list(pack.manifest.permissions),
                "effective_permissions": self._effective_permissions(pack),
                "touches": [
                    "its own domain tables",
                    *(["app views"] if pack.projections.app else []),
                    *(["managed markdown notes"] if pack.projections.markdown else []),
                    *[
                        f"{name.replace('_', ' ')} capability"
                        for name in sorted(pack.capabilities)
                    ],
                ],
                "files": sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()),
            }
        )
        return result

    def install(self, source: Path, *, force: bool = False) -> dict[str, Any]:
        """Install a validated external pack and return a lifecycle receipt."""
        preview = self.preview(source)
        if preview["would_replace"] and not force:
            raise FileExistsError(f"pack already installed: {preview['name']}")
        if preview["would_replace"]:
            return self.upgrade(source)
        pack = self.add(Path(source), force=False)
        self._record(pack)
        return {"status": "installed", "pack": self._summary(pack), "permissions": preview["declared_permissions"]}

    def activate(self, name: str) -> DomainPack:
        """Mark an installed pack active and re-apply its declarative schema."""
        pack = self.get_by_alias(name)
        if pack is None:
            raise KeyError(f"unknown installed pack: {name}")
        self._workspace_pack_root(pack)
        apply_pack_schema(pack, self.ws.domains_db, self.ws.ledger_db)
        self._record(pack, active=True)
        self.reload()
        activated = self.get(pack.name)
        if activated is None:
            raise ValueError(f"pack failed validation after activation: {pack.name}")
        return activated

    def upgrade(self, source: Path) -> dict[str, Any]:
        """Snapshot and replace an installed pack, then apply its schema."""
        root = self._safe_source(source)
        incoming = load_pack(root, validate=True)
        installed = self.ws.packs_dir / incoming.name
        backup = self._snapshot(incoming.name) if installed.exists() else None
        pack = self.add(root, force=True)
        self._record(pack, backup=backup)
        return {
            "status": "upgraded" if backup else "installed",
            "pack": self._summary(pack),
            "backup": str(backup) if backup else None,
        }

    def rollback(self, name: str, backup: Path | None = None) -> dict[str, Any]:
        """Restore the latest (or explicitly supplied) pack snapshot."""
        source = Path(backup) if backup is not None else None
        if source is None:
            candidates = sorted(self._backup_dir.glob(f"{name}-*"))
            if not candidates:
                raise FileNotFoundError(f"no backup available for {name}")
            source = candidates[-1]
        source = self._safe_source(source)
        backup_root = self._backup_dir.resolve()
        if source != backup_root and backup_root not in source.parents:
            raise ValueError("rollback source must be a pack backup")
        pack = load_pack(source, validate=True)
        if pack.name != name:
            raise ValueError(f"backup belongs to {pack.name}, not {name}")
        destination = self.ws.packs_dir / name
        if destination.is_symlink():
            raise ValueError(f"installed pack path is a symlink: {name}")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, symlinks=False)
        restored = load_pack(destination, validate=True)
        apply_pack_schema(restored, self.ws.domains_db, self.ws.ledger_db)
        self._record(restored, active=True)
        self.reload()
        return {"status": "rolled_back", "pack": self._summary(restored), "backup": str(source)}

    def export(self, name: str, destination: Path) -> dict[str, Any]:
        """Export an installed pack without following symlinks."""
        pack = self.get_by_alias(name)
        if pack is None:
            raise KeyError(f"unknown installed pack: {name}")
        self._workspace_pack_root(pack)
        dest = Path(destination).expanduser()
        if dest.exists():
            raise FileExistsError(f"export destination exists: {dest}")
        if dest.resolve() == pack.root or pack.root in dest.resolve().parents:
            raise ValueError("export destination cannot be inside the installed pack")
        shutil.copytree(pack.root, dest, symlinks=False)
        return {"status": "exported", "pack": self._summary(pack), "destination": str(dest.resolve())}

    def uninstall(self, name: str) -> dict[str, Any]:
        """Snapshot and remove an installed pack and its generated tables."""
        pack = self.get_by_alias(name)
        if pack is None:
            raise KeyError(f"unknown installed pack: {name}")
        # Lane D compiles cross-pack links to real foreign keys, so removing
        # a pack that other records point at would break those references.
        # Refuse while anything still points here, and say what to clear.
        blockers = uninstall_blockers(pack.name, self.list(), self.ws.domains_db)
        if blockers:
            raise ValueError(f"{pack.name} cannot be removed yet. " + " ".join(blockers))
        self._workspace_pack_root(pack)
        backup = self._snapshot(pack.name)
        destination = self.ws.packs_dir / pack.name
        shutil.rmtree(destination)
        domains = connect_rw(self.ws.domains_db)
        try:
            for object_type in pack.objects:
                domains.execute(f'DROP TABLE IF EXISTS "{table_name(pack.name, object_type)}"')
            domains.commit()
        finally:
            domains.close()
        ledger = connect_rw(self.ws.ledger_db)
        try:
            for table, column in (
                ("schema_registry", "domain"),
                ("apply_policy", "domain"),
                ("pack_install", "name"),
            ):
                ledger.execute(f"DELETE FROM {table} WHERE {column} = ?", (pack.name,))
            ledger.execute(
                "DELETE FROM projection_outbox WHERE object_key LIKE ?",
                (f"{pack.name}:%",),
            )
            ledger.execute(
                "DELETE FROM projection_watermark WHERE object_key LIKE ?",
                (f"{pack.name}:%",),
            )
            ledger.commit()
        finally:
            ledger.close()
        metadata = self._metadata()
        metadata["packs"].pop(pack.name, None)
        self._save_metadata(metadata)
        self.reload()
        return {"status": "uninstalled", "name": pack.name, "backup": str(backup)}

    def add(self, src: Path, *, force: bool = False) -> DomainPack:
        safe_src = self._safe_source(src)
        pack = install_pack(safe_src, self.ws.packs_dir, force=force)
        write_migration(pack)
        apply_pack_schema(pack, self.ws.domains_db, self.ws.ledger_db)
        self._record(pack)
        self.reload()
        installed = self.get(pack.name)
        if installed is None:
            raise ValueError(f"pack failed validation after install: {pack.name}")
        return installed

    def activate_bundled(self, name: str) -> DomainPack:
        """Install a bundled pack (e.g. plants, sourdough) into the workspace."""
        src = bundled_packs_root() / name
        if not src.is_dir():
            raise FileNotFoundError(f"bundled pack not found: {name}")
        return self.add(src, force=True)

    def ensure_schemas_applied(self) -> None:
        for pack in self.list():
            apply_pack_schema(pack, self.ws.domains_db, self.ws.ledger_db)
