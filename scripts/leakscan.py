#!/usr/bin/env python3
"""Leak gates for the public repo (P0).

Blocks:
  - tracked *.sqlite / *.db files
  - binary blobs outside an allowlist
  - forbidden remote URLs in .git/config (private Hermes remotes)
  - optional private denylist file (DOMAIN_FOUNDRY_DENYLIST path)

Synthetic fixtures must live under examples/synthetic/.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BLOCKED_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
ALLOWED_BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
}
FORBIDDEN_REMOTE_RE = re.compile(
    r"(HermesWorkspace|finn.?hermes|/Users/[^/]+/Hermes)", re.IGNORECASE
)


def _git_ls_files() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    if not out:
        return []
    return [ROOT / p for p in out.decode().split("\0") if p]


def _is_probably_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:8192]
    except OSError:
        return False
    return b"\0" in chunk


def scan() -> list[str]:
    errors: list[str] = []
    files = _git_ls_files()

    for path in files:
        rel = path.relative_to(ROOT)
        if path.suffix.lower() in BLOCKED_SUFFIXES:
            errors.append(f"blocked database file tracked: {rel}")
        if path.suffix.lower() not in ALLOWED_BINARY_SUFFIXES and _is_probably_binary(path):
            # allow source maps / lockfiles that may contain null? unlikely
            if path.suffix.lower() not in {".lock"}:
                errors.append(f"binary file not on allowlist: {rel}")

    # Remote URL check
    git_config = ROOT / ".git" / "config"
    if git_config.exists():
        text = git_config.read_text(encoding="utf-8", errors="replace")
        if FORBIDDEN_REMOTE_RE.search(text):
            errors.append("forbidden private remote URL detected in .git/config")

    denylist = os.environ.get("DOMAIN_FOUNDRY_DENYLIST")
    if denylist:
        deny_path = Path(denylist)
        if deny_path.exists():
            needles = [
                line.strip()
                for line in deny_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            for path in files:
                if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff2"}:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for needle in needles:
                    if needle in text:
                        errors.append(
                            f"denylist hit {needle!r} in {path.relative_to(ROOT)}"
                        )
        else:
            errors.append(f"DOMAIN_FOUNDRY_DENYLIST set but missing: {deny_path}")

    return errors


def main() -> int:
    errors = scan()
    if errors:
        print("leakscan FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("leakscan OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
