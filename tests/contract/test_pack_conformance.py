"""Standalone pack-author conformance contract."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COFFEE = REPO / "examples" / "heldout" / "packs" / "coffee"

_SPEC = importlib.util.spec_from_file_location(
    "pack_conformance", REPO / "scripts" / "pack_conformance.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
run = _MODULE.run


def test_pack_conformance_emits_pass_for_external_fixture():
    report = run(COFFEE)
    assert report["format"] == "domain-foundry-pack-conformance/1"
    assert report["status"] == "pass"
    assert report["checks"]["routing"]["failures"] == []
    assert report["checks"]["lifecycle"]["orphan_tables"] == []


def test_pack_conformance_reports_deep_validation_failure(tmp_path: Path):
    hostile = tmp_path / "coffee"
    shutil.copytree(COFFEE, hostile)
    migrations = hostile / "migrations"
    migrations.mkdir()
    (migrations / "evil.sql").write_text("DROP TABLE coffee__brew;", encoding="utf-8")

    report = run(hostile)
    assert report["status"] == "fail"
    assert report["checks"]["deep_validation"]["passed"] is False
    assert "destructive" in report["checks"]["deep_validation"]["error"]
