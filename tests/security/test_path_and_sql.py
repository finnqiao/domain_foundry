from __future__ import annotations

from pathlib import Path

import pytest

from domain_foundry_core.security.paths import PathSafetyError, safe_join
from domain_foundry_core.security.redact import redact_secrets
from domain_foundry_core.security.store import is_readonly_sql


def test_safe_join_rejects_traversal(tmp_path: Path):
    base = tmp_path / "vault"
    base.mkdir()
    ok = safe_join(base, "Notes/bake.md")
    assert ok == (base / "Notes/bake.md").resolve()

    with pytest.raises(PathSafetyError):
        safe_join(base, "../escape.txt")
    with pytest.raises(PathSafetyError):
        safe_join(base, "/etc/passwd")
    with pytest.raises(PathSafetyError):
        safe_join(base, "")


def test_redact_secrets_common_patterns():
    samples = [
        "sk-abcdefghijklmnopqrstuvwxyz012345",
        "ghp_abcdefghijklmnopqrstuvwx",
        "AKIAIOSFODNN7EXAMPLE",
        "api_key=supersecretvalue123",
    ]
    for s in samples:
        out = redact_secrets(f"prefix {s} suffix")
        assert s not in out
        assert "[REDACTED]" in out


def test_readonly_sql_allowlist():
    assert is_readonly_sql("SELECT * FROM entry")
    assert is_readonly_sql("WITH x AS (SELECT 1) SELECT * FROM x")
    assert not is_readonly_sql("DELETE FROM entry")
    assert not is_readonly_sql("SELECT 1; DROP TABLE entry")
    assert not is_readonly_sql("ATTACH DATABASE 'x' AS y")
