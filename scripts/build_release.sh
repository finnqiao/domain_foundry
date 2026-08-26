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

echo "==> 1/7 SPA dependencies + exact bundled-license notices"
(
  cd app
  npm ci
)
"$DF_PYTHON" scripts/dependency_license_audit.py --verify-source-texts

echo "==> 2/7 SPA production build"
(
  cd app
  npm run build
)

echo "==> 3/7 stage SPA into the package"
scripts/stage_webapp.sh

echo "==> 4/7 build sdist + wheel"
rm -rf "$ROOT/dist"
"$DF_PYTHON" -m pip install --quiet --upgrade build twine
"$DF_PYTHON" -m build

echo "==> 5/7 wheel content assertions"
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
require(
    "_webapp/THIRD_PARTY_NOTICES.txt",
    "bundled JavaScript license notices are missing",
)
for pack in ("food", "plants", "sourdough", "travel", "japanese", "health", "dev", "x_radar"):
    require(f"_bundled/{pack}/pack.yaml", "packs/ force-include is incomplete")
require(
    "examples/heldout/wizard_hobby_suite.jsonl",
    "the held-out wizard suite must ship for acceptance at runtime",
)
require(
    "examples/heldout/foundry_interest_suite.yaml",
    "the independent Foundry interest suite must ship for release evaluation",
)
require(
    "foundry/_knowledge/source-registry.yaml",
    "the evidence registry must ship for FoundrySpec validation",
)
require(
    "foundry/_golden/sourdough-lab.foundry.yaml",
    "the reviewed foundry goldens must ship",
)
print(f"wheel contents OK ({len(names)} entries): {wheel}")
PY

echo "==> 6/7 SPDX SBOM with resolved runtime licenses"
"$DF_PYTHON" scripts/generate_sbom.py --output dist/domain-foundry-core-0.1.0.spdx.json

echo "==> 7/7 twine check"
"$DF_PYTHON" -m twine check dist/*.whl dist/*.tar.gz

echo "release artifacts ready in dist/"
