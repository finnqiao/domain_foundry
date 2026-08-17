#!/usr/bin/env bash
# TestPyPI gate preflight. This script is deliberately no-upload: it checks
# the local release artifact and runs the clean-machine proof, then leaves any
# TestPyPI publish/install decision to a human with the appropriate credentials.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi
cd "$ROOT"

if [[ ! -e "$ROOT/dist" ]]; then
  echo "no dist/ — run scripts/build_release.sh" >&2
  exit 2
fi
shopt -s nullglob
artifacts=("$ROOT"/dist/*)
if (( ${#artifacts[@]} == 0 )); then
  echo "no release artifacts in dist/ — run scripts/build_release.sh" >&2
  exit 2
fi

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  DF_PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  DF_PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  DF_PYTHON=python
else
  echo "error: Python 3 is required for the TestPyPI preflight" >&2
  exit 1
fi

echo "==> local package metadata check (no upload)"
"$DF_PYTHON" -m twine check "$ROOT"/dist/*

echo "==> clean-machine artifact smoke (no credentials)"
bash "$ROOT/scripts/clean_machine_gate.sh"

echo "TestPyPI preflight OK. No upload was performed."
echo "A human must separately decide whether to publish this exact version to TestPyPI and run its install smoke."
