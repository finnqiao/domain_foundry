#!/usr/bin/env bash
# Serve domain-foundry for the Playwright E2E suite (app/playwright.config.ts).
#
# Hermetic: a throwaway DOMAIN_FOUNDRY_HOME per run, initialized before serving.
# Requires the SPA to be built (app/dist) — the FastAPI app serves those files.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${E2E_PORT:-8790}"

if [[ ! -f "$ROOT/app/dist/index.html" ]]; then
  echo "e2e_server: app/dist/index.html missing — run 'npm run build' in app/ first" >&2
  exit 1
fi

# Same venv convention as scripts/release_audit.sh.
if [[ -x "$ROOT/.venv/bin/domain-foundry" ]]; then
  export PATH="$ROOT/.venv/bin:$PATH"
fi
command -v domain-foundry >/dev/null 2>&1 || {
  echo "e2e_server: domain-foundry CLI not on PATH (pip install -e .)" >&2
  exit 1
}

DOMAIN_FOUNDRY_HOME="$(mktemp -d "${TMPDIR:-/tmp}/df-e2e.XXXXXX")"
export DOMAIN_FOUNDRY_HOME

domain-foundry init

domain-foundry serve --host 127.0.0.1 --port "$PORT" &
SERVER_PID=$!
cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$DOMAIN_FOUNDRY_HOME"
}
trap cleanup EXIT INT TERM
wait "$SERVER_PID"
