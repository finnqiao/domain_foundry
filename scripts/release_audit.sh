#!/usr/bin/env bash
# Release-blocking audit for the public repo (P9).
#
# Aggregates every gate that must pass before a tag/publish. Fails fast and
# prints a legible per-check result. Run from anywhere; resolves the repo root.
#
#   scripts/release_audit.sh
#
# Checks:
#   1. leakscan            — no tracked *.sqlite/binaries, no private remotes, denylist
#   2. clock audit         — no datetime.now()/time.time() outside the clock provider
#   3. no tracked databases — belt-and-suspenders over leakscan
#   4. git history origin  — first commit is the P0 bootstrap (no pre-P0 import)
#   5. ruff                — lint clean
#   6. pytest              — full suite green
#   7. mkdocs build        — docs site builds (skipped if mkdocs absent)
#   8. eval corpus replay  — routing gate vs committed baseline (skipped if CLI absent)

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=1; }
skip() { printf '  \033[33mSKIP\033[0m  %s\n' "$1"; }

run() { # <label> <cmd...>
  local label="$1"; shift
  if "$@" >/tmp/release_audit.$$ 2>&1; then
    pass "$label"
  else
    bad "$label"
    sed 's/^/        /' /tmp/release_audit.$$ | tail -20
  fi
  rm -f /tmp/release_audit.$$
}

echo "== domain_expert release audit =="

run "leakscan"        python scripts/leakscan.py
run "clock audit"     python scripts/clock_audit.py

# No tracked database files (independent of leakscan's own check).
if git ls-files | grep -Eiq '\.(sqlite|sqlite3|db)$'; then
  bad "no tracked database files"
else
  pass "no tracked database files"
fi

# Git history must start at the P0 bootstrap (no private import, §12.1).
first_subject="$(git log --reverse --format=%s | head -1)"
if printf '%s' "$first_subject" | grep -Eiq 'bootstrap|P0'; then
  pass "git history starts at P0 ($first_subject)"
else
  bad "git history first commit is not a P0 bootstrap: $first_subject"
fi

run "ruff"            ruff check core tests scripts adapters
run "pytest"          python -m pytest -q

if command -v mkdocs >/dev/null 2>&1; then
  run "mkdocs build"  mkdocs build --quiet
else
  skip "mkdocs build (mkdocs not installed; pip install -e '.[docs]')"
fi

if command -v domain-expert >/dev/null 2>&1; then
  run "eval corpus replay" domain-expert eval --full --min-accuracy 0.9
else
  skip "eval corpus replay (domain-expert CLI not on PATH)"
fi

echo
if [ "$fail" -eq 0 ]; then
  printf '\033[32mrelease audit OK\033[0m\n'
else
  printf '\033[31mrelease audit FAILED\033[0m\n'
fi
exit "$fail"
