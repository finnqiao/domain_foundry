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
        / "provider_compatibility_audit.py"
    )
    spec = importlib.util.spec_from_file_location("provider_compatibility_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = _module()


def test_current_provider_compatibility_evidence_matches_code() -> None:
    assert AUDIT.audit(as_of=date(2026, 8, 19)) == []


def test_provider_registry_fails_when_model_default_drifts(tmp_path: Path) -> None:
    document = yaml.safe_load(AUDIT.REGISTRY_PATH.read_text(encoding="utf-8"))
    changed = deepcopy(document)
    changed["providers"][1]["routine_model"] = "retired-model"
    path = tmp_path / "providers.yaml"
    path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
    errors = AUDIT.audit(as_of=date(2026, 8, 19), path=path)
    assert any("executable default" in error for error in errors)


def test_provider_registry_fails_closed_when_research_is_stale() -> None:
    errors = AUDIT.audit(as_of=date(2026, 9, 19))
    assert any("stale" in error for error in errors)
