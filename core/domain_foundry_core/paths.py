"""Workspace path resolution for ~/.domain_foundry/."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "domain_foundry"
ENV_HOME = "DOMAIN_FOUNDRY_HOME"
# Colon/os.pathsep-separated dirs of personal (or extra) packs outside the OSS tree.
# Example: DOMAIN_FOUNDRY_PACKS_PATH=~/HermesWorkspace/packs
ENV_PACKS_PATH = "DOMAIN_FOUNDRY_PACKS_PATH"


def default_home() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / f".{APP_NAME}").resolve()


def overlay_pack_dirs() -> list[Path]:
    """Extra pack roots from DOMAIN_FOUNDRY_PACKS_PATH (private overlay).

    Each entry may be either a directory containing pack subdirs, or a single
    pack directory (one that itself has pack.yaml). Missing paths are skipped.

    ``DOMAIN_FOUNDRY_PACKS`` is accepted as a deprecated alias for the same value.
    """
    raw = os.environ.get(ENV_PACKS_PATH) or os.environ.get("DOMAIN_FOUNDRY_PACKS") or ""
    if not raw.strip():
        return []
    out: list[Path] = []
    seen: set[Path] = set()
    for part in raw.split(os.pathsep):
        part = part.strip()
        if not part:
            continue
        path = Path(part).expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


class Workspace:
    """Resolved on-disk layout for one install."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = (home or default_home()).resolve()
        self.db_dir = self.home / "db"
        self.packs_dir = self.home / "packs"
        self.attachments_dir = self.home / "attachments"
        self.vault_dir = self.home / "vault"
        self.blocks_dir = self.home / "blocks"
        self.ledger_db = self.db_dir / "ledger.sqlite"
        self.domains_db = self.db_dir / "domains.sqlite"

    def ensure_layout(self) -> None:
        for p in (
            self.home,
            self.db_dir,
            self.packs_dir,
            self.attachments_dir,
            self.vault_dir,
            self.blocks_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)

    def db_path(self, name: str) -> Path:
        if name == "ledger":
            return self.ledger_db
        if name == "domains":
            return self.domains_db
        raise ValueError(f"unknown database {name!r}; expected ledger|domains")
