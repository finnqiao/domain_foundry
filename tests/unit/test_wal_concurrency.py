"""Mesh P0 substrate contract: WAL + busy_timeout on every RW connection.

Two invariants:
  1. connect_rw puts the database into WAL mode with a nonzero busy_timeout.
  2. A second *process* holding a write lock delays — but does not fail —
     this process's write (busy_timeout waits it out).
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from domain_foundry_core.security.store import connect_ro, connect_rw

LOCK_HOLDER = r"""
import sqlite3, sys, time
conn = sqlite3.connect(sys.argv[1])
conn.execute("PRAGMA busy_timeout=5000")
conn.execute("BEGIN IMMEDIATE")
conn.execute("INSERT INTO t (v) VALUES ('from-subprocess')")
print("LOCKED", flush=True)
time.sleep(float(sys.argv[2]))
conn.commit()
print("RELEASED", flush=True)
"""


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "wal_test.sqlite"
    conn = connect_rw(db)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.commit()
    conn.close()
    return db


def test_connect_rw_enables_wal_and_busy_timeout(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    conn = connect_rw(db)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    finally:
        conn.close()
    # WAL is persistent: a plain reader sees the mode too.
    ro = connect_ro(db)
    try:
        assert ro.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        ro.close()


def test_concurrent_writer_waits_instead_of_erroring(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    hold_seconds = 1.5
    proc = subprocess.Popen(
        [sys.executable, "-c", LOCK_HOLDER, str(db), str(hold_seconds)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "LOCKED"

        conn = connect_rw(db)
        try:
            start = time.monotonic()
            # Without busy_timeout this raises "database is locked" immediately.
            conn.execute("INSERT INTO t (v) VALUES ('from-test-process')")
            conn.commit()
            waited = time.monotonic() - start
        finally:
            conn.close()

        assert waited < 5.0, "should succeed within the busy_timeout window"
        assert proc.wait(timeout=10) == 0

        check = connect_ro(db)
        try:
            rows = {r["v"] for r in check.execute("SELECT v FROM t")}
        finally:
            check.close()
        assert rows == {"from-subprocess", "from-test-process"}
    finally:
        if proc.poll() is None:
            proc.kill()
