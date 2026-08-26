from __future__ import annotations

import importlib.util
from copy import deepcopy
from datetime import date
from pathlib import Path

import yaml


def _module():  # type: ignore[no-untyped-def]
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "dependency_license_audit.py"
    )
    spec = importlib.util.spec_from_file_location("dependency_license_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = _module()


def test_shipped_dependency_closure_has_reviewed_licenses_and_exact_notices() -> None:
    errors, counts = AUDIT.audit(
        as_of=date(2026, 8, 19), verify_source_texts=True
    )
    assert errors == []
    assert counts == {"python_runtime": 33, "npm_runtime_occurrences": 42}


def test_dependency_license_registry_fails_closed_on_lock_drift(tmp_path: Path) -> None:
    document = yaml.safe_load(AUDIT.POLICY_PATH.read_text(encoding="utf-8"))
    changed = deepcopy(document)
    changed["python_runtime"] = changed["python_runtime"][1:]
    path = tmp_path / "dependency-licenses.yaml"
    path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
    errors, _counts = AUDIT.audit(as_of=date(2026, 8, 19), policy_path=path)
    assert any("unreviewed Python runtime dependency" in error for error in errors)


def test_dependency_license_review_expires() -> None:
    errors, _counts = AUDIT.audit(as_of=date(2026, 11, 18))
    assert any("stale" in error for error in errors)


def test_bundled_notices_are_bound_to_the_npm_lock() -> None:
    notices = AUDIT.NOTICES_PATH.read_text(encoding="utf-8")
    assert f"package-lock.json SHA-256: {AUDIT.sha256_file(AUDIT.NPM_LOCK)}" in notices
    assert "murmurhash-js 1.0.0 — MIT" in notices
    assert "Copyright (c) 2011 Gary Court" in notices
