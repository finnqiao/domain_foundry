"""Installed pack registry — discovery + activation."""

from __future__ import annotations

from pathlib import Path

from domain_expert_core.ledger.migrate import ensure_migrated
from domain_expert_core.packs.loader import (
    bundled_packs_root,
    discover_entry_point_packs,
    discover_pack_dirs,
    install_pack,
    load_pack,
)
from domain_expert_core.packs.models import DomainPack
from domain_expert_core.packs.schema_compiler import apply_pack_schema, write_migration
from domain_expert_core.paths import Workspace


class PackRegistry:
    def __init__(self, workspace: Workspace | None = None) -> None:
        self.ws = workspace or Workspace()
        self.ws.ensure_layout()
        ensure_migrated(self.ws.ledger_db, "ledger")
        ensure_migrated(self.ws.domains_db, "domains")
        self._packs: dict[str, DomainPack] = {}
        self.reload()

    def search_paths(self) -> list[Path]:
        # Only installed/workspace packs are active. Bundled packs are a catalog
        # (see bundled_catalog / activate_bundled) — not auto-enabled.
        return [self.ws.packs_dir]

    def bundled_catalog(self) -> list[Path]:
        return discover_pack_dirs([bundled_packs_root()])

    def reload(self) -> None:
        self._packs.clear()
        dirs = discover_pack_dirs(self.search_paths()) + discover_entry_point_packs()
        for d in dirs:
            try:
                pack = load_pack(d, validate=True)
            except Exception:
                continue
            self._packs[pack.name] = pack

    def list(self) -> list[DomainPack]:
        return sorted(self._packs.values(), key=lambda p: p.name)

    def get(self, name: str) -> DomainPack | None:
        return self._packs.get(name)

    def get_by_alias(self, name_or_alias: str) -> DomainPack | None:
        if name_or_alias in self._packs:
            return self._packs[name_or_alias]
        for pack in self._packs.values():
            if name_or_alias in pack.manifest.aliases:
                return pack
        return None

    def validate(self, name: str | None = None) -> list[str]:
        """Return list of error strings (empty = ok)."""
        targets = [self._packs[name]] if name and name in self._packs else self.list()
        errors: list[str] = []
        for pack in targets:
            try:
                load_pack(pack.root, validate=True)
            except Exception as exc:
                errors.append(f"{pack.name}: {exc}")
        return errors

    def add(self, src: Path, *, force: bool = False) -> DomainPack:
        pack = install_pack(src, self.ws.packs_dir, force=force)
        write_migration(pack)
        apply_pack_schema(pack, self.ws.domains_db, self.ws.ledger_db)
        self.reload()
        return self._packs[pack.name]

    def activate_bundled(self, name: str) -> DomainPack:
        """Install a bundled pack (e.g. plants, sourdough) into the workspace."""
        src = bundled_packs_root() / name
        if not src.is_dir():
            raise FileNotFoundError(f"bundled pack not found: {name}")
        return self.add(src, force=True)

    def ensure_schemas_applied(self) -> None:
        for pack in self.list():
            apply_pack_schema(pack, self.ws.domains_db, self.ws.ledger_db)
