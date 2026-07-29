#!/usr/bin/env bash
# Stage the built SPA into the Python package so it ships inside the wheel.
#
# app/dist is a build artifact (gitignored), so a wheel built straight from a
# checkout contains no web app — `pipx install domain-foundry-core` +
# `domain-foundry serve` would then serve JSON instead of the app the quickstart
# promises. Run this between `npm run build` and `python -m build`:
#
#   cd app && npm ci && npm run build && cd ..
#   scripts/stage_webapp.sh
#   python -m build --wheel
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/app/dist"
DEST="$ROOT/core/domain_foundry_core/_webapp"

if [[ ! -f "$SRC/index.html" ]]; then
  echo "error: $SRC/index.html not found — run 'cd app && npm run build' first" >&2
  exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$SRC/." "$DEST/"
echo "staged $(find "$DEST" -type f | wc -l | tr -d ' ') file(s) into core/domain_foundry_core/_webapp"
