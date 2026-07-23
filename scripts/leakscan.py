#!/usr/bin/env python3
"""Leak gates for the public Domain Foundry repo.

Blocks:
  - tracked *.sqlite / *.db files
  - binary blobs outside an allowlist
  - forbidden remote URLs in .git/config (private Hermes remotes)
  - personal-string content heuristics (home paths, emails, Telegram tokens,
    API-key shapes)
  - optional private denylist file (DOMAIN_FOUNDRY_DENYLIST path)

Synthetic fixtures must live under examples/synthetic/.
Do not rewrite git history — report findings and fix the working tree.
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

# Content heuristics for personal/PII leakage (tracked text files).
PERSONAL_PATH_RE = re.compile(r"/Users/finn(?:/|\b)")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# OpenAI/Anthropic-ish, GitHub PATs, AWS access key ids, Slack, Telegram bots.
API_KEY_RE = re.compile(
    r"\b(?:"
    r"sk-[A-Za-z0-9_\-]{16,}"
    r"|sk-proj-[A-Za-z0-9_\-]{16,}"
    r"|rk-[A-Za-z0-9_\-]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[baprs]-[A-Za-z0-9\-]{10,}"
    r")\b"
)
TELEGRAM_TOKEN_RE = re.compile(r"\b\d{8,12}:[A-Za-z0-9_\-]{30,}\b")
TELEGRAM_ID_RE = re.compile(
    r"(?i)\b(?:telegram[_\- ]?(?:chat[_\- ]?|user[_\- ]?)?id|chat_id|tg_user_id)"
    r"\s*[:=]\s*-?\d{5,}\b"
)

# Paths that intentionally document or exercise these patterns.
CONTENT_ALLOWLIST_PREFIXES = (
    "scripts/leakscan.py",
    "scripts/check_remotes.sh",
    "docs/LEAK_AUDIT.md",
    "docs/LEAKSCAN_PHASE9.md",
    "docs/FOUNDER_VALIDATION.md",
    "docs/PRIVATE_OVERLAY.md",
    "examples/synthetic/",
    "tests/",
)

# Emails / key suffixes treated as synthetic fixtures, not leaks.
EMAIL_ALLOW_SUFFIXES = (
    "@example.com",
    "@example.org",
    "@example.net",
    "@localhost",
    "@corp.io",  # sanitizer fixture domain
    "@test.local",
)

TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".txt",
    ".sh",
    ".css",
    ".html",
    ".jinja",
    ".j2",
}


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


def _content_allowlisted(rel: Path) -> bool:
    s = rel.as_posix()
    return any(s == p or s.startswith(p) for p in CONTENT_ALLOWLIST_PREFIXES)


def _email_allowed(addr: str) -> bool:
    lower = addr.lower()
    if any(lower.endswith(sfx) for sfx in EMAIL_ALLOW_SUFFIXES):
        return True
    if "noreply" in lower or lower.startswith("your@"):
        return True
    # SSH remotes look email-shaped (git@github.com:org/repo.git).
    if lower in {"git@github.com", "git@gitlab.com", "git@bitbucket.org"}:
        return True
    return False


def _key_looks_synthetic(text: str, match: re.Match[str]) -> bool:
    """Skip tokens that are clearly EXAMPLE / fixture placeholders."""
    window = text[match.start() : min(len(text), match.end() + 12)]
    return "EXAMPLE" in window.upper() or "FIXTURE" in window.upper()


def scan_personal_content(files: list[Path], *, root: Path | None = None) -> list[str]:
    """Return finding strings for personal-string heuristics (path + pattern kind)."""
    base = root or ROOT
    errors: list[str] = []
    for path in files:
        try:
            rel = path.relative_to(base)
        except ValueError:
            rel = path
        if _content_allowlisted(rel):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if PERSONAL_PATH_RE.search(text):
            errors.append(f"pattern=personal_home_path path={rel.as_posix()}")
        for m in API_KEY_RE.finditer(text):
            if _key_looks_synthetic(text, m):
                continue
            errors.append(f"pattern=api_key_shape path={rel.as_posix()}")
            break
        if TELEGRAM_TOKEN_RE.search(text):
            errors.append(f"pattern=telegram_bot_token path={rel.as_posix()}")
        if TELEGRAM_ID_RE.search(text):
            errors.append(f"pattern=telegram_id path={rel.as_posix()}")
        for m in EMAIL_RE.finditer(text):
            addr = m.group(0)
            if _email_allowed(addr):
                continue
            # Report pattern only — do not echo the address (may be real).
            errors.append(f"pattern=email path={rel.as_posix()}")
            break
    return errors


def scan() -> list[str]:
    errors: list[str] = []
    files = _git_ls_files()

    for path in files:
        rel = path.relative_to(ROOT)
        if path.suffix.lower() in BLOCKED_SUFFIXES:
            errors.append(f"blocked database file tracked: {rel}")
        if path.suffix.lower() not in ALLOWED_BINARY_SUFFIXES and _is_probably_binary(path):
            if path.suffix.lower() not in {".lock"}:
                errors.append(f"binary file not on allowlist: {rel}")

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
                            f"pattern=denylist path={path.relative_to(ROOT).as_posix()}"
                        )
                        break
        else:
            errors.append(f"DOMAIN_FOUNDRY_DENYLIST set but missing: {deny_path}")

    # Personal-string content scan. Opt out with DOMAIN_FOUNDRY_LEAKSCAN_CONTENT=0.
    if os.environ.get("DOMAIN_FOUNDRY_LEAKSCAN_CONTENT", "1") not in {"0", "false", "no"}:
        errors.extend(scan_personal_content(files, root=ROOT))

    return errors


def main() -> int:
    errors = scan()
    if errors:
        print("leakscan FAILED:")
        for e in errors:
            print(f"  - {e}")
        print(f"leakscan findings: {len(errors)}")
        return 1
    print("leakscan OK")
    print("leakscan findings: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
