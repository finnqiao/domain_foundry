from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():  # type: ignore[no-untyped-def]
    path = Path(__file__).resolve().parents[2] / "scripts" / "foundry_heldout_audit.py"
    spec = importlib.util.spec_from_file_location("foundry_heldout_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_heldout_suite_is_independent_and_actionable() -> None:
    assert _module().audit() == []
