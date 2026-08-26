#!/usr/bin/env bash
# Produce the exact machine evidence an independent reviewer receives.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi
cd "$ROOT"

OUTPUT="${1:-$ROOT/release/evidence}"
mkdir -p "$OUTPUT"

echo "==> aggregate machine gate"
scripts/release_audit.sh 2>&1 | tee "$OUTPUT/release_audit.log"

echo "==> reproducible package build"
scripts/build_release.sh 2>&1 | tee "$OUTPUT/build_release.log"

echo "==> clean-machine installed-wheel gate"
scripts/clean_machine_gate.sh 2>&1 | tee "$OUTPUT/clean_machine.log"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  DF_PYTHON="$ROOT/.venv/bin/python"
else
  DF_PYTHON=python3
fi

"$DF_PYTHON" scripts/release_evidence.py \
  --output "$OUTPUT/candidate.json" \
  --release-audit-log "$OUTPUT/release_audit.log" \
  --build-release-log "$OUTPUT/build_release.log" \
  --clean-machine-log "$OUTPUT/clean_machine.log"

echo "candidate evidence ready: $OUTPUT/candidate.json"
