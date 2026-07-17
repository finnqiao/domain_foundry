"""Plain-SQL migration runner with schema_version tracking."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from domain_foundry_core.clock import now_iso
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_rw

_VERSION_RE = re.compile(r"^(ledger|domains)_(\d+)_")
_MIGRATIONS_ROOT = Path(__file__).resolve().parent.parent / "migrations"


def migrations_root() -> Path:
    return _MIGRATIONS_ROOT


def migration_files(db: str) -> list[tuple[int, Path]]:
    root = migrations_root() / db
    if not root.is_dir():
        return []
    out: list[tuple[int, Path]] = []
    for f in sorted(root.glob(f"{db}_*.sql")):
        m = _VERSION_RE.match(f.name)
        if m and m.group(1) == db:
            out.append((int(m.group(2)), f))
    return sorted(out)


def schema_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return int(row["v"]) if row and row["v"] is not None else 0


def read_schema_version(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    conn = connect_rw(db_path)
    try:
        return schema_version(conn)
    finally:
        conn.close()


def ensure_migrated(db_path: Path, db: str) -> int:
    """Apply pending migrations for `db` (`ledger` or `domains`). Returns version."""
    conn = connect_rw(db_path)
    try:
        current = schema_version(conn)
        for version, path in migration_files(db):
            if version <= current:
                continue
            sql = path.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, now_iso()),
            )
            conn.commit()
            current = version
        return schema_version(conn)
    finally:
        conn.close()


def init_workspace(home: Path | None = None) -> dict[str, int]:
    """Create layout and migrate both databases. Returns {db: version}."""
    ws = Workspace(home)
    ws.ensure_layout()
    return {
        "ledger": ensure_migrated(ws.ledger_db, "ledger"),
        "domains": ensure_migrated(ws.domains_db, "domains"),
    }
