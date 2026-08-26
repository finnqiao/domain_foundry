from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_audit_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "knowledge_audit.py"
    spec = importlib.util.spec_from_file_location("knowledge_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reviewed_knowledge_corpus_is_internally_consistent() -> None:
    module = _load_audit_module()
    assert module.audit() == []
