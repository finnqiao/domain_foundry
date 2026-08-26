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
#   6. pyright             — type-check clean (the same step CI runs)
#   7. pytest              — full suite green
#   8. mkdocs build        — docs site builds; a missing tool is a failed environment
#   9. eval corpus replay  — routing gate vs committed baseline; never skipped
#  10. docs claims check   — no hardcoded test counts / known-false claims in public docs
#  11. knowledge audit     — source licensing, freshness, and principle closure
#  12. dependency licenses — shipped closure is reviewed and notices are exact
#  13. provider audit      — live model defaults match fresh official evidence
#  14. name audit          — public coordinates have fresh, honestly scoped evidence
#  15. foundry audit       — three goldens, reproducible compiler, schema, owned app
#  16. held-out leak check — the protected interest set has not been tuned into

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Use the repo venv when it exists, so the audit gives the same answer whether or
# not you remembered to activate it. Without this, `python`/`domain-foundry` are
# missing (3 checks FAIL, 2 SKIP) and `ruff` resolves to whatever version happens
# to be on PATH — which reports rules the pinned version doesn't have.
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  export PATH="$ROOT/.venv/bin:$PATH"
fi

# Hermetic workspace: the audit must give the same answer as CI regardless of
# what lives in the operator's real ~/.domain_foundry (or whether one exists).
DOMAIN_FOUNDRY_HOME="$(mktemp -d "${TMPDIR:-/tmp}/df-audit.XXXXXX")"
export DOMAIN_FOUNDRY_HOME
trap 'rm -rf "$DOMAIN_FOUNDRY_HOME"' EXIT

fail=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=1; }
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

echo "== domain_foundry release audit =="

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
# Pyright was absent here while GitHub Actions `ci` ran it, so this script
# reported 8/8 for twelve days over a red CI — and because Pyright runs before
# pytest in the workflow, the test suite never ran there either. The local
# aggregate gate must never be weaker than the one that blocks a merge.
run "pyright"         pyright
run "pytest"          python -m pytest -q

if command -v mkdocs >/dev/null 2>&1; then
  run "mkdocs build"  mkdocs build --strict --quiet
else
  bad "mkdocs build (mkdocs missing; install .[docs])"
fi

run "docs claims check" python scripts/docs_claims_check.py
run "knowledge audit"   python scripts/knowledge_audit.py
run "dependency license audit" python scripts/dependency_license_audit.py --verify-source-texts
run "provider compatibility" python scripts/provider_compatibility_audit.py
run "name collision evidence" python scripts/name_availability_audit.py
run "foundry audit"     python scripts/foundry_audit.py
run "foundry held-out"  python scripts/foundry_heldout_audit.py
# The protected 20-interest set may not be fed back into the atlas or the
# visible suite. A held-out miss is a compiler bug; widening the atlas to
# cover one is the move this catches.
run "interest held-out leak check" python scripts/heldout_leakcheck.py
run "SPDX SBOM"         python scripts/generate_sbom.py --output "$DOMAIN_FOUNDRY_HOME/sbom.spdx.json" --created 2026-08-19T12:00:00Z

if command -v uv >/dev/null 2>&1 && command -v pip-audit >/dev/null 2>&1; then
  export UV_CACHE_DIR="$DOMAIN_FOUNDRY_HOME/uv-cache"
  run "Python locked dependency export" uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file "$DOMAIN_FOUNDRY_HOME/requirements.txt"
  run "Python vulnerability audit" pip-audit --strict --no-deps --disable-pip --cache-dir "$DOMAIN_FOUNDRY_HOME/pip-audit-cache" -r "$DOMAIN_FOUNDRY_HOME/requirements.txt"
else
  bad "Python vulnerability audit (uv or pip-audit missing; install .[dev])"
fi

if command -v npm >/dev/null 2>&1; then
  # Do not start a login shell here. On machines with more than one Node
  # installation, shell startup can replace the already-resolved Node with a
  # binary for another architecture, making Rollup's locked native package
  # appear missing even after a correct `npm ci`.
  run "app production dependency audit" bash -c 'cd app && npm audit --omit=dev --audit-level=high'
  run "app lint"                        bash -c 'cd app && npm run lint'
  run "app unit tests"                  bash -c 'cd app && npm test'
  run "app production build"            bash -c 'cd app && npm run build'
  if [[ -x "$ROOT/app/node_modules/.bin/playwright" ]]; then
    run "app browser E2E" bash -c 'cd app && npx playwright test'
  else
    bad "app browser E2E (Playwright missing; run npm ci in app/)"
  fi
else
  bad "app checks (npm missing)"
fi

if command -v domain-foundry >/dev/null 2>&1; then
  run "init (hermetic home)" domain-foundry init
  run "eval corpus replay" domain-foundry eval --full --min-accuracy 0.9
else
  bad "eval corpus replay (domain-foundry CLI missing; install .[dev])"
fi

echo
if [ "$fail" -eq 0 ]; then
  printf '\033[32mrelease audit OK\033[0m\n'
else
  printf '\033[31mrelease audit FAILED\033[0m\n'
fi
exit "$fail"
