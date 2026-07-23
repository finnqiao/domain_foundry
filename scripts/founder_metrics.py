#!/usr/bin/env python3
"""Print founder-validation aggregate metrics from a DomainFoundry home.

Reads only counts (no personal text). Default home: foundry-dry prove-out mirror.

  DOMAIN_FOUNDRY_HOME=~/HermesWorkspace/foundry-dry \\
    python scripts/founder_metrics.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from domain_foundry_core.paths import Workspace  # noqa: E402


def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(
            f'SELECT count(*) FROM "{table}" WHERE IFNULL(tombstoned,0)=0'
        ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        try:
            row = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error:
            return 0


def main() -> int:
    home = Path(
        os.environ.get("DOMAIN_FOUNDRY_HOME", "")
        or (Path.home() / "HermesWorkspace" / "foundry-dry")
    ).expanduser()
    ws = Workspace(home)
    out: dict = {"home": str(ws.home), "domains": {}, "ledger": {}}
    if ws.domains_db.exists():
        conn = sqlite3.connect(f"file:{ws.domains_db}?mode=ro", uri=True)
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1"
                )
            ]
            for t in tables:
                if t.startswith("sqlite_") or t in {"schema_version", "domains_meta"}:
                    continue
                n = _count(conn, t)
                if n:
                    out["domains"][t] = n
        finally:
            conn.close()
    if ws.ledger_db.exists():
        conn = sqlite3.connect(f"file:{ws.ledger_db}?mode=ro", uri=True)
        try:
            for t in ("capture_event", "entry", "canonical_object", "change_request"):
                n = _count(conn, t)
                if n:
                    out["ledger"][t] = n
        finally:
            conn.close()

    # Migration rollup (synthetic-safe aggregates for FOUNDER_VALIDATION).
    jp_v = out["domains"].get("japanese__jp_vocab", 0)
    jp_g = out["domains"].get("japanese__jp_grammar", 0)
    food = sum(v for k, v in out["domains"].items() if k.startswith("food__"))
    health = sum(v for k, v in out["domains"].items() if k.startswith("health__"))
    dev = sum(v for k, v in out["domains"].items() if k.startswith("dev__"))
    travel = sum(v for k, v in out["domains"].items() if k.startswith("travel__"))
    out["rollup"] = {
        "japanese_vocab": jp_v,
        "japanese_grammar": jp_g,
        "food_objects": food,
        "health_objects": health,
        "dev_objects": dev,
        "travel_objects": travel,
        "entries": out["ledger"].get("entry", 0),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
