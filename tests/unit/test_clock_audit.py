"""Frozen-clock injection audit: no bare wall-clock reads under core/ (§10.2)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_clock_audit() -> Any:
    """Load the script as a module. Untyped by nature — it is exec'd
    from a path, so its constants (ROOT/CORE/ALLOWLIST) are not visible
    to a type checker. Returning Any documents that rather than hiding it."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "clock_audit.py"
    spec = importlib.util.spec_from_file_location("clock_audit", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_core_has_no_bare_wall_clock_reads():
    mod = _load_clock_audit()
    violations = mod.audit()
    assert violations == [], "\n".join(violations)


def test_audit_detects_injected_violation(tmp_path: Path):
    """Guard the guard: a bare datetime.now() outside clock.py must be caught."""
    mod = _load_clock_audit()
    fake_core = tmp_path / "core" / "domain_foundry_core"
    fake_core.mkdir(parents=True)
    (fake_core / "clock.py").write_text(
        "from datetime import datetime\n\ndef now():\n    return datetime.now()\n",
        encoding="utf-8",
    )
    (fake_core / "bad.py").write_text(
        "from datetime import datetime\n\nx = datetime.utcnow()\n",
        encoding="utf-8",
    )
    original_root, original_core = mod.ROOT, mod.CORE
    try:
        mod.ROOT = tmp_path
        mod.CORE = fake_core
        mod.ALLOWLIST = {fake_core / "clock.py"}
        violations = mod.audit()
    finally:
        mod.ROOT, mod.CORE = original_root, original_core
        mod.ALLOWLIST = {original_core / "clock.py"}
    assert any("bad.py" in v for v in violations)
    assert all("clock.py" not in v for v in violations)
