#!/usr/bin/env bash
# Live hermes-agent ↔ domain-foundry smoke (synthetic only).
#
# - Does NOT switch the sticky Hermes profile / default gateway
# - Uses a throwaway DOMAIN_FOUNDRY_HOME
# - Reinstalls the adapter into the Hermes venv via uv (Hermes often has no pip)
# - Exercises: capture bake → capture dining → ambiguous correct
# - Optional: live LLM oneshot when HERMES_LIVE=1
#
# Usage:
#   scripts/hermes_e2e_smoke.sh
#   HERMES_LIVE=1 scripts/hermes_e2e_smoke.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_PY="${HERMES_PY:-$HOME/.hermes/hermes-agent/venv/bin/python}"
HERMES_BIN="${HERMES_BIN:-$(command -v hermes || true)}"
PROFILE="${HERMES_PROFILE:-domainfoundry}"
PORT="${DOMAIN_FOUNDRY_PORT:-8788}"
URL="http://127.0.0.1:${PORT}"
# Always use a fresh throwaway home unless DF_SMOKE_HOME is set explicitly.
# Do not inherit DOMAIN_FOUNDRY_HOME from the caller — that often points at a
# prior trial and breaks pack add.
DF_HOME="${DF_SMOKE_HOME:-$(mktemp -d /tmp/df-hermes-e2e-XXXXXX)}"
FRICTION_LOG="${FRICTION_LOG:-$DF_HOME/friction.log}"
export DOMAIN_FOUNDRY_HOME="$DF_HOME"

log() { printf '%s\n' "$*" | tee -a "$FRICTION_LOG"; }
friction() { log "FRICTION: $*"; }

cleanup() {
  if [[ -n "${SERVE_PID:-}" ]] && kill -0 "$SERVE_PID" 2>/dev/null; then
    kill "$SERVE_PID" 2>/dev/null || true
    wait "$SERVE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

: >"$FRICTION_LOG"
log "DF_HOME=$DF_HOME"
log "URL=$URL"
log "PROFILE=$PROFILE"

if [[ ! -x "$HERMES_PY" ]]; then
  friction "Hermes venv python missing at $HERMES_PY"
  exit 1
fi
if [[ -z "$HERMES_BIN" ]]; then
  friction "hermes CLI not on PATH"
  exit 1
fi

# --- ensure isolated profile exists (never switches sticky default) ----------
if ! hermes profile list 2>/dev/null | grep -q "[[:space:]]${PROFILE}[[:space:]]"; then
  log "Creating isolated profile '$PROFILE' (--clone keys/config from active)"
  hermes profile create "$PROFILE" --clone \
    --description "Domain Foundry E2E — synthetic only"
else
  log "Reusing existing profile '$PROFILE'"
fi

# Sticky default must remain whichever ◆ was already set
if hermes profile list 2>/dev/null | grep -q "◆${PROFILE}"; then
  friction "sticky default is $PROFILE — expected caller default left alone"
fi

# --- install / upgrade adapter into Hermes env ------------------------------
if ! command -v uv >/dev/null 2>&1; then
  friction "uv not on PATH; Hermes venvs often lack pip — install uv or use hermes python -m ensurepip"
  exit 1
fi
log "uv pip install -e adapters/hermes_agent + core into Hermes venv"
uv pip install --python "$HERMES_PY" -U -e "$ROOT/adapters/hermes_agent" -e "$ROOT" >/dev/null

# Entry point must load a *module* (Hermes calls module.register)
"$HERMES_PY" - <<'PY' || { friction "entry point does not load a module with register()"; exit 1; }
from importlib.metadata import entry_points
eps = list(entry_points().select(group="hermes_agent.plugins"))
assert eps, "no hermes_agent.plugins entry points"
e = next(x for x in eps if x.name == "domain_foundry")
mod = e.load()
assert hasattr(mod, "register"), f"expected module.register, got {type(mod)}"
print("entry_point_ok", e.value)
PY

# --- enable plugin + toolset on profile only (pip plugins invisible to CLI) -
"$HERMES_PY" - <<PY
from pathlib import Path
import yaml
p = Path.home() / ".hermes" / "profiles" / "$PROFILE" / "config.yaml"
cfg = yaml.safe_load(p.read_text()) or {}
plugins = cfg.setdefault("plugins", {})
enabled = list(plugins.get("enabled") or [])
if "domain_foundry" not in enabled:
    enabled.append("domain_foundry")
plugins["enabled"] = enabled
pt = cfg.setdefault("platform_toolsets", {})
cli = list(pt.get("cli") or [])
if "domain_foundry" not in cli:
    cli.append("domain_foundry")
pt["cli"] = sorted(set(cli))
known = cfg.setdefault("known_plugin_toolsets", {})
kcli = list(known.get("cli") or [])
if "domain_foundry" not in kcli:
    kcli.append("domain_foundry")
known["cli"] = sorted(set(kcli))
p.write_text(yaml.safe_dump(cfg, sort_keys=False))
print("profile_config_ok")
PY

# Confirm default ~/.hermes/config.yaml was not mutated
if grep -q "domain_foundry" "$HOME/.hermes/config.yaml" 2>/dev/null; then
  friction "default ~/.hermes/config.yaml contains domain_foundry (isolation broken)"
fi

# --- throwaway harness ------------------------------------------------------
export PATH="$ROOT/.venv/bin:$PATH"
export DOMAIN_FOUNDRY_HOME="$DF_HOME"
domain-foundry --home "$DF_HOME" init >/dev/null
domain-foundry --home "$DF_HOME" pack add --force "$ROOT/packs/sourdough" >/dev/null
domain-foundry --home "$DF_HOME" pack add --force "$ROOT/packs/food" >/dev/null

domain-foundry --home "$DF_HOME" serve --host 127.0.0.1 --port "$PORT" &
SERVE_PID=$!
for _ in $(seq 1 50); do
  if curl -sf "$URL/api/health" >/dev/null; then break; fi
  sleep 0.1
done
curl -sf "$URL/api/health" >/dev/null || { friction "serve failed to become healthy on $URL"; exit 1; }
log "serve healthy"

# --- direct tool path (no LLM; in-process writes per mesh P0) ---------------
# DOMAIN_FOUNDRY_URL is intentionally NOT exported to the tool block: that env
# var forces the HTTP client, and HTTP writes 410 since mesh P0.
"$HERMES_PY" - <<'PY' | tee -a "$FRICTION_LOG"
import json, os
from domain_foundry_hermes_agent import build_tools
from domain_foundry_hermes_agent.local import LocalHarnessClient

tools = {t.name: t for t in build_tools(LocalHarnessClient(os.environ["DOMAIN_FOUNDRY_HOME"]))}
c1 = tools["domain_foundry_capture"](
    text="baked a 75% hydration country loaf, bulk 5h, came out great",
    source_ref="smoke-bake",
)
c2 = tools["domain_foundry_capture"](
    text="dinner at Olive Grove: grilled octopus and a glass of assyrtiko",
    source_ref="smoke-dining",
)
corr = tools["domain_foundry_correct"](text="that bake was 80% hydration not 75")
print("CAPTURE_BAKE", c1.get("status"), [r.get("domain") for r in c1.get("routed", [])])
print("CAPTURE_DINING", c2.get("status"), [r.get("domain") for r in c2.get("routed", [])])
print("CORRECT_TARGET", corr.get("object_uid"), "applied=", corr.get("applied"))
uid = corr.get("object_uid") or ""
if not uid.startswith("sourdough:bake:"):
    print("FRICTION: ambiguous correction hit", uid, "expected sourdough bake")
PY

# --- HTTP server stays a read-only viewer: writes must 410 -------------------
WRITE_STATUS="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/api/capture" \
  -H 'Content-Type: application/json' -d '{"text": "should be rejected"}')"
log "HTTP_WRITE_STATUS $WRITE_STATUS"
if [[ "$WRITE_STATUS" != "410" ]]; then
  friction "expected 410 on HTTP write, got $WRITE_STATUS"
fi

# --- optional live LLM oneshot ----------------------------------------------
if [[ "${HERMES_LIVE:-0}" == "1" ]]; then
  log "HERMES_LIVE=1 — running oneshot capture via hermes -p $PROFILE"
  hermes -p "$PROFILE" -z \
    "I baked a 72% hydration boule today, 4h bulk. Capture via Domain Foundry tools verbatim." \
    --yolo | tee -a "$FRICTION_LOG" | tail -20
fi

log "OK — smoke finished. Friction log: $FRICTION_LOG"
log "Throwaway home kept at $DF_HOME (delete when done). Default Hermes profile untouched."
