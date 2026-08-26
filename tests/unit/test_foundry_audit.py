from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():  # type: ignore[no-untyped-def]
    path = Path(__file__).resolve().parents[2] / "scripts" / "foundry_audit.py"
    spec = importlib.util.spec_from_file_location("foundry_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_foundry_release_contract_is_closed_and_reproducible() -> None:
    assert _module().audit() == []
