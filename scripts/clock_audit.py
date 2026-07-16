#!/usr/bin/env python3
"""Frozen-clock injection audit (plan §10.2).

Evals and contract tests must never read wall time. This enforces that no module
under ``core/`` reads the real clock directly: the only sanctioned wall-clock
read lives in the injectable clock provider (``clock.py``). Everything else must
call ``domain_expert_core.clock.now()`` / ``now_iso()`` so a frozen clock can be
injected in tests and eval replays.

Bans, outside the allowlist:
  - ``datetime.now(...)``
  - ``datetime.utcnow(...)``
  - ``time.time()`` / ``time.monotonic()`` (wall/real clocks)

Run: ``python scripts/clock_audit.py``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core" / "domain_expert_core"

# Only the clock provider may read wall time.
ALLOWLIST = {CORE / "clock.py"}

_PATTERNS = [
    re.compile(r"\bdatetime\.now\s*\("),
    re.compile(r"\bdatetime\.utcnow\s*\("),
    re.compile(r"\btime\.time\s*\("),
    re.compile(r"\btime\.monotonic\s*\("),
]


def audit() -> list[str]:
    violations: list[str] = []
    for path in sorted(CORE.rglob("*.py")):
        if path in ALLOWLIST:
            continue
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            code = line.split("#", 1)[0]
            for pat in _PATTERNS:
                if pat.search(code):
                    rel = path.relative_to(ROOT)
                    violations.append(
                        f"{rel}:{lineno}: bare wall-clock read; use "
                        f"domain_expert_core.clock instead -> {line.strip()}"
                    )
    return violations


def main() -> int:
    violations = audit()
    if violations:
        print("clock_audit FAILED:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("clock_audit OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
