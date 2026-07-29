#!/usr/bin/env bash
# Clean-machine quickstart gate (plan §11 P8) — the automatable slice.
#
# Fresh workspace → add food + travel packs → validate → capture a single-domain
# message and a cross-domain (dining↔trip) message → assert both routed as
# expected. Exercises only the public CLI, exactly as the docs describe.
#
# Usage: scripts/quickstart_gate.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

HOME_DIR="$(mktemp -d)"
trap 'rm -rf "$HOME_DIR"' EXIT
export DOMAIN_FOUNDRY_HOME="$HOME_DIR"

de() { domain-foundry "$@"; }

echo "==> init ($HOME_DIR)"
de init

# Onboarding: the README's first command. --no-probe keeps the gate offline and
# key-free; the live-probe path is a human gate (see LAUNCH_CHECKLIST.md §1).
echo "==> setup (bring-your-own-key, non-interactive)"
de setup --provider anthropic --routine claude-haiku-4-5 --sota claude-opus-5 \
  -y --no-probe >/dev/null
test -f "$HOME_DIR/config.toml" || { echo "FAIL: setup wrote no config.toml"; exit 1; }
de setup --show | python -c "
import sys, json
s = json.load(sys.stdin)
assert s['provider'] == 'anthropic', s['provider']
assert s['routine']['model'] == 'claude-haiku-4-5', s['routine']
assert s['sota']['model'] == 'claude-opus-5', s['sota']
# No key was supplied, so neither tier may claim to be live.
assert not s['routine']['live'] and not s['sota']['live'], s
print('  provider=%s routine=%s sota=%s' % (
    s['provider'], s['routine']['model'], s['sota']['model']))
"
# An exported env var must still win over what setup just wrote.
DOMAIN_FOUNDRY_SOTA_MODEL=claude-sonnet-5 de setup --show | python -c "
import sys, json
assert json.load(sys.stdin)['sota']['model'] == 'claude-sonnet-5', 'env must override config'
print('  env override -> claude-sonnet-5')
"

echo "==> add + validate packs"
de pack add packs/food
de pack add packs/travel
de pack validate food
de pack validate travel

echo "==> capture (single domain: food.cook)"
out1="$(de capture 'cooked a batch of shoyu ramen, came out great')"
echo "$out1" | python -c "import sys,json; r=json.load(sys.stdin); ds=[x['domain'] for x in r['routed']]; assert 'food' in ds, ds; print('  routed ->', ds)"

echo "==> capture (cross domain: food.dining + travel.trip)"
out2="$(de capture 'dinner at River Station Grill and heading to Port City in March')"
echo "$out2" | python -c "import sys,json; r=json.load(sys.stdin); ds={x['domain'] for x in r['routed']}; assert {'food','travel'} <= ds, ds; print('  routed ->', sorted(ds))"

echo "==> query food"
de query --domain food >/dev/null

# Expert on-ramp: a structured source through the mapping-driven importer.
# dry-run → apply → re-apply must be preview / write / no-op.
echo "==> import (structured source: dry-run, apply, idempotent re-apply)"
assert_import() {
  python -c "
import sys, json
want_key, want_val = sys.argv[1], int(sys.argv[2])
raw = sys.stdin.read()
d = json.loads(raw[raw.find('{'):raw.rfind('}') + 1])
assert d['complete'], 'reconciliation incomplete: %r' % d
assert d[want_key] == want_val, '%s=%r, expected %d' % (want_key, d[want_key], want_val)
print('  %s=%d complete=%s' % (want_key, d[want_key], d['complete']))
" "$1" "$2"
}
de import -m examples/importers/travel.yaml --json tests/fixtures/importers/travel/ \
  | assert_import would_import 8
de import -m examples/importers/travel.yaml --json tests/fixtures/importers/travel/ --apply \
  | assert_import imported 8
de import -m examples/importers/travel.yaml --json tests/fixtures/importers/travel/ --apply \
  | assert_import skipped_existing 8

echo "PASS: quickstart gate green"
