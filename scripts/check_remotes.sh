#!/usr/bin/env bash
# Pre-push guard: refuse remotes that point at private Hermes sources.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if git -C "$ROOT" remote -v 2>/dev/null | grep -Eiq 'HermesWorkspace|finn.?hermes'; then
  echo "Refusing push: private Hermes remote detected. Public repo must stay fresh." >&2
  exit 1
fi
exit 0
