"""Workspace path resolution for ~/.domain_expert/."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "domain_expert"
ENV_HOME = "DOMAIN_EXPERT_HOME"


def default_home() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / f".{APP_NAME}").resolve()


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
