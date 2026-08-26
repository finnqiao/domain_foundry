#!/usr/bin/env bash
# Gate 0: install the newest built wheel into a fresh virtualenv and prove the
# activation loop on a machine that has never seen this checkout. No API keys
# or provider credentials are needed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

shopt -s nullglob
wheels=("$ROOT"/dist/*.whl)
if (( ${#wheels[@]} == 0 )); then
  echo "no wheel — run scripts/build_release.sh" >&2
  exit 1
fi
WHEEL="${wheels[0]}"
for candidate in "${wheels[@]}"; do
  if [[ "$candidate" -nt "$WHEEL" ]]; then
    WHEEL="$candidate"
  fi
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/domain-foundry-gate.XXXXXX")"
export DOMAIN_FOUNDRY_HOME="$WORK/home"
export DOMAIN_FOUNDRY_LLM=heuristic
unset \
  ANTHROPIC_API_KEY \
  DEEPSEEK_API_KEY \
  DOMAIN_FOUNDRY_API_TOKEN \
  DOMAIN_FOUNDRY_LLM_API_KEY \
  DOMAIN_FOUNDRY_LLM_BASE_URL \
  DOMAIN_FOUNDRY_LLM_MODEL \
  DOMAIN_FOUNDRY_PACKS \
  DOMAIN_FOUNDRY_PACKS_PATH \
  DOMAIN_FOUNDRY_ROUTINE_API_KEY \
  DOMAIN_FOUNDRY_ROUTINE_BASE_URL \
  DOMAIN_FOUNDRY_ROUTINE_MODEL \
  DOMAIN_FOUNDRY_SOTA_API_KEY \
  DOMAIN_FOUNDRY_SOTA_BASE_URL \
  DOMAIN_FOUNDRY_SOTA_MODEL \
  OPENAI_API_KEY \
  OPENROUTER_API_KEY

if command -v python3 >/dev/null 2>&1; then
  DF_PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  DF_PYTHON=python
else
  echo "error: Python 3 is required to run the clean-machine gate" >&2
  exit 1
fi

VENV="$WORK/venv"
PORT="${DF_GATE_PORT:-8790}"
SERVER_PID=""
cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "==> fresh venv + install from wheel"
"$DF_PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install --quiet "$WHEEL"
DF="$VENV/bin/domain-foundry"

echo "==> init + setup (no probe, no keys) + doctor"
"$DF" init
"$DF" setup --provider none --non-interactive --no-probe
"$DF" doctor

echo "==> compile a shipped FoundrySpec from the installed wheel"
"$DF" foundry goldens | "$VENV/bin/python" -c \
  'import json, sys; specs = json.load(sys.stdin); assert len(specs) == 3, specs'
"$VENV/bin/python" - "$WORK/foundry-app" <<'PY'
from pathlib import Path
import sys

from domain_foundry_core.foundry import FoundryCompiler, load_golden_specs

target = Path(sys.argv[1])
specs = load_golden_specs()
assert len(specs) == 3, specs
artifact = FoundryCompiler().compile(specs[0], target)
for path in (
    artifact.app,
    artifact.schema,
    artifact.spec,
    artifact.evidence,
    artifact.receipt,
):
    assert path.is_file() and path.stat().st_size > 0, path
PY

echo "==> activate a bundled pack + capture + query"
"$DF" pack add sourdough
RECEIPT="$("$DF" capture --json "baked a 75% hydration country loaf, came out great")"
printf '%s\n' "$RECEIPT" | "$VENV/bin/python" -c \
  'import json, sys; receipt = json.load(sys.stdin); assert receipt["status"] == "applied", receipt'
"$DF" query --domain sourdough | "$VENV/bin/python" -c \
  'import json, sys; rows = json.load(sys.stdin); assert rows, "query empty"'

echo "==> serve smoke: / is the SPA, /api/packs is JSON"
"$DF" serve --port "$PORT" >"$WORK/server.log" 2>&1 &
SERVER_PID=$!
ready=0
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/api/packs" >/dev/null; then
    ready=1
    break
  fi
  sleep 0.5
done
if (( ready == 0 )); then
  echo "server did not become ready" >&2
  sed -n '1,160p' "$WORK/server.log" >&2 || true
  exit 1
fi
curl -fsS "http://127.0.0.1:$PORT/" | grep -qi "<!doctype html" \
  || { echo "FAIL: / did not serve the SPA (wheel missing _webapp?)" >&2; exit 1; }
NOTICES="$WORK/THIRD_PARTY_NOTICES.txt"
curl -fsS "http://127.0.0.1:$PORT/THIRD_PARTY_NOTICES.txt" -o "$NOTICES" \
  || { echo "FAIL: bundled dependency notices are not served" >&2; exit 1; }
grep -q "DOMAIN FOUNDRY THIRD-PARTY NOTICES" "$NOTICES" \
  || { echo "FAIL: bundled dependency notices have unexpected content" >&2; exit 1; }
curl -fsS "http://127.0.0.1:$PORT/api/packs" | "$VENV/bin/python" -c \
  'import json, sys; body = json.load(sys.stdin); assert any(p["name"] == "sourdough" for p in body["packs"])'
curl -fsS "http://127.0.0.1:$PORT/passions/sourdough" | grep -qi "<!doctype html" \
  || { echo "FAIL: deep link did not serve the SPA (S1.1 catch-all)" >&2; exit 1; }

echo "==> restart: data survives a new process"
kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
SERVER_PID=""
"$DF" query --domain sourdough | "$VENV/bin/python" -c \
  'import json, sys; rows = json.load(sys.stdin); assert rows, "data lost across restart"'
"$DF" health >/dev/null

echo "CLEAN MACHINE GATE: PASS"
