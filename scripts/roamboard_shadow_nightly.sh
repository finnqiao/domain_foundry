#!/usr/bin/env bash
# Nightly Roamboard↔DomainFoundry shadow diff (Phase 7).
# Does NOT flip launchd or mutate travel.sqlite. Record one day of the ≥7-day gate.
#
# Usage:
#   export DOMAIN_FOUNDRY_HOME=~/HermesWorkspace/foundry-dry
#   export DOMAIN_FOUNDRY_REPO=/path/to/domain_foundry
#   ./scripts/roamboard_shadow_nightly.sh
#
# Optional: ROAMBOARD_FEED=/path/to/feed.json TRAVEL_DB=~/HermesWorkspace/travel/data/travel.sqlite
set -euo pipefail

REPO="${DOMAIN_FOUNDRY_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
HOME_DF="${DOMAIN_FOUNDRY_HOME:?set DOMAIN_FOUNDRY_HOME}"
FEED="${ROAMBOARD_FEED:-$REPO/tests/fixtures/roamboard/feed.json}"
TRAVEL_DB="${TRAVEL_DB:-$HOME/HermesWorkspace/travel/data/travel.sqlite}"
LOG_DIR="${HOME_DF}/shadow/roamboard"
mkdir -p "$LOG_DIR"

export PYTHONPATH="${REPO}/core:${REPO}/adapters/roamboard/src${PYTHONPATH:+:$PYTHONPATH}"
PY="${REPO}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then PY=python3; fi

DAY="$(date -u +%Y-%m-%d)"
OUT="$LOG_DIR/nightly-${DAY}.log"

{
  echo "=== roamboard shadow ${DAY}Z ==="
  "$PY" -m domain_foundry_core.cli --home "$HOME_DF" roamboard sync --shadow \
    --feed "$FEED" \
    --travel-db "$TRAVEL_DB"
  echo "=== end ==="
} 2>&1 | tee "$OUT"

# Append a one-line streak counter (human reviews zero-diff days).
STREAK="$LOG_DIR/ZERO_DIFF_STREAK.txt"
SUMMARY="$(ls -1dt "$LOG_DIR"/20*Z/SUMMARY.md 2>/dev/null | head -1 || true)"
if [[ -n "$SUMMARY" ]] && rg -q 'zero_diff[^\\n]*:\\s*\\*\\*True\\*\\*|zero_diff.: true' "$SUMMARY" 2>/dev/null; then
  echo "$DAY zero-diff" >>"$STREAK"
else
  echo "$DAY HAS-DIFFS — reset streak review" >>"$STREAK"
fi

echo "Wrote $OUT (streak log: $STREAK)"
echo "Cutover requires ≥7 consecutive zero-diff days — do not flip launchd here."
