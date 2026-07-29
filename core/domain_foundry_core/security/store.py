"""RO/RW SQLite connection discipline + integrity helpers."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

_READONLY_RE = re.compile(
    r"^\s*(SELECT|WITH|PRAGMA\s+TABLE_INFO|EXPLAIN)\b", re.IGNORECASE
)
_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|"
    r"VACUUM|REINDEX|PRAGMA\s+(?!table_info))\b",
    re.IGNORECASE,
)


def last_row_id(cur: sqlite3.Cursor) -> int:
    """The rowid an INSERT just produced.

    ``sqlite3.Cursor.lastrowid`` is typed ``int | None`` because it is None when
    the last statement was not an INSERT. Call sites here always follow an
    INSERT, so the None branch is unreachable — but it was being handled three
    different ways across the codebase (``int(x)``, ``int(x or 0)``, and
    ``int(x) if x else None``), which means one of them silently substituted 0
    for a missing rowid. Raise instead: a missing rowid after an INSERT is a
    broken invariant, not a zero.
    """
    rowid = cur.lastrowid
    if rowid is None:
        raise RuntimeError("INSERT produced no rowid")
    return rowid


def connect_rw(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Mesh P0: multiple long-lived processes (Concierge, Domain Experts, CLI)
    # share these databases. WAL allows concurrent readers alongside one
    # writer; busy_timeout makes the rare cross-domain write overlap wait
    # instead of erroring out.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def connect_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"database not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def is_readonly_sql(sql: str) -> bool:
    sql = (sql or "").strip().rstrip(";")
    if not sql or ";" in sql:
        return False
    if not _READONLY_RE.match(sql):
        return False
    if _FORBIDDEN_RE.search(sql):
        return False
    return True


def integrity_check(path: Path) -> dict[str, Any]:
    """Run integrity_check + foreign_key_check. Returns a health dict."""
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "ok": False,
            "integrity": "missing",
            "fk_violations": [],
        }
    conn = connect_rw(path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        fk_violations = [dict(r) for r in fk_rows]
        return {
            "path": str(path),
            "exists": True,
            "ok": integrity == "ok" and not fk_violations,
            "integrity": integrity,
            "fk_violations": fk_violations,
        }
    finally:
        conn.close()
