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
export DOMAIN_EXPERT_HOME="$HOME_DIR"

de() { domain-expert "$@"; }

echo "==> init ($HOME_DIR)"
de init

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

echo "PASS: quickstart gate green"
