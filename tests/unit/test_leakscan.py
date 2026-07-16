from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


def _load_leakscan():
    script = Path(__file__).resolve().parents[2] / "scripts" / "leakscan.py"
    spec = importlib.util.spec_from_file_location("leakscan", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_leakscan_rejects_fake_sqlite(tmp_path: Path):
    """Guard the guard: a tracked sqlite must fail leakscan when present in a repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.check_call(["git", "init", "-b", "main"], cwd=repo)
    bad = repo / "secret.sqlite"
    bad.write_bytes(b"SQLite format 3\x00fake")
    subprocess.check_call(["git", "add", "secret.sqlite"], cwd=repo)

    ls = _load_leakscan()
    original = ls.ROOT
    try:
        ls.ROOT = repo
        errors = ls.scan()
    finally:
        ls.ROOT = original
    assert any("blocked database file" in e for e in errors)
