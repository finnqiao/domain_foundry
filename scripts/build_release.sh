#!/usr/bin/env bash
# Build the release artifacts exactly as LAUNCH_CHECKLIST.md §3 prescribes:
# SPA build → stage into the package → sdist + wheel → content assertions →
# twine check. Fails loudly at the first missing release surface.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  DF_PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  DF_PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  DF_PYTHON=python
else
  echo "error: Python 3 is required to build the release" >&2
  exit 1
fi

echo "==> 1/5 SPA build (npm ci for a reproducible tree)"
(
  cd app
  npm ci
  npm run build
)

echo "==> 2/5 stage SPA into the package"
scripts/stage_webapp.sh

echo "==> 3/5 build sdist + wheel"
rm -rf "$ROOT/dist"
"$DF_PYTHON" -m pip install --quiet --upgrade build twine
"$DF_PYTHON" -m build

echo "==> 4/5 wheel content assertions"
"$DF_PYTHON" - <<'PY'
from pathlib import Path
import zipfile

wheels = sorted(Path("dist").glob("*.whl"), key=lambda path: path.stat().st_mtime)
assert wheels, "no wheel in dist/"
wheel = wheels[-1]
with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()


def require(fragment: str, why: str) -> None:
    assert any(fragment in name for name in names), (
        f"wheel missing {fragment!r} — {why}"
    )


require("_webapp/index.html", "run scripts/stage_webapp.sh before building")
require("_webapp/assets/", "SPA assets not staged")
for pack in ("food", "plants", "sourdough", "travel", "japanese", "health", "dev", "x_radar"):
    require(f"_bundled/{pack}/pack.yaml", "packs/ force-include is incomplete")
require(
    "examples/heldout/wizard_hobby_suite.jsonl",
    "the held-out wizard suite must ship for acceptance at runtime",
)
print(f"wheel contents OK ({len(names)} entries): {wheel}")
PY

echo "==> 5/5 twine check"
"$DF_PYTHON" -m twine check dist/*

echo "release artifacts ready in dist/"
