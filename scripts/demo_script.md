# Domain Foundry — Slice 1 activation demo storyboard

This is a reusable storyboard, not recording evidence. Follow it against one
fresh local workspace and the exact artifact being demonstrated. The recording
described by [`LAUNCH_CHECKLIST.md`](../LAUNCH_CHECKLIST.md) §2 remains a human
gate; do not create or publish a GIF from this file alone.

The default path is deterministic and local: it uses the bundled synthetic
`sourdough` pack, a fresh `DOMAIN_FOUNDRY_HOME`, and the heuristic router. It
does not need a provider key and it makes no external network calls. Use
synthetic text only. Keep the terminal at roughly 100×28 and the browser at
roughly 1280×800; do not cut away while a receipt or correction is visible.

## Truth boundary

- Record only values and labels that are visible in the run. IDs, timestamps,
  confidence values, projection status, and export paths are run-specific.
- `domain-foundry eval export` is an eval/regression-case export, not a user
  data export. Never substitute it for the canonical export beat below.
- The current uncommitted source includes the Slice 1 Today / Your passions /
  Inbox / Settings shell, `/create`, the Log/Ask Composer, model-confirm and
  scaffold/repair states, URL routing, and the local `GET /api/export` surface.
  The top-level `domain-foundry export --out` command is also available as the
  copy-pasteable canonical export beat. The checkout's ignored `app/dist` may
  be older than this source; record only against a rebuilt artifact whose
  visible UI matches the script. Do not describe the source tree as a packaged
  release.
- Only record a model-confirm card, live/scaffold badge, Ask citation, or export
  receipt when that exact control and receipt are present in the artifact under
  test. Never hard-code a provider, model, price, score, or “live” claim.
- This synthetic run demonstrates a mechanism. It does not claim that a human
  gate passed, that a real provider key worked, that the ten-minute test passed,
  or that a generated domain is production-ready.

## Pre-roll (not recorded)

Run from the repository root. For a packaged artifact, set `DEMO_DF_BIN` to
the installed command and set `DEMO_PACK_SOURCE=sourdough`; for this checkout,
the defaults below use the existing local virtualenv and `packs/sourdough`.
The repository contains `scripts/build_release.sh` and
`scripts/clean_machine_gate.sh`, but the release builder invokes `npm ci` and
package installation. This storyboard does not run those network-capable
build steps; use an already-prepared command/artifact and do not describe the
release or clean-machine gates as passed.

```bash
# Use an already-installed local command. For a wheel install, use:
#   DEMO_DF_BIN=domain-foundry DEMO_PACK_SOURCE=sourdough
export DEMO_DF_BIN="${DEMO_DF_BIN:-.venv/bin/domain-foundry}"
export DEMO_PACK_SOURCE="${DEMO_PACK_SOURCE:-packs/sourdough}"
if [[ "$DEMO_DF_BIN" == */* ]]; then
  test -x "$DEMO_DF_BIN"
else
  command -v "$DEMO_DF_BIN" >/dev/null
fi || {
  echo "Set DEMO_DF_BIN to the domain-foundry command under test." >&2
  exit 1
}

export DOMAIN_FOUNDRY_HOME="$(mktemp -d)"
export DOMAIN_FOUNDRY_LLM=heuristic
unset DOMAIN_FOUNDRY_PACKS_PATH

"$DEMO_DF_BIN" version
"$DEMO_DF_BIN" setup --provider none -y --no-probe
"$DEMO_DF_BIN" setup --show

# If the server is started in another terminal, paste these two lines there.
printf 'export DOMAIN_FOUNDRY_HOME=%q\nexport DEMO_DF_BIN=%q\n' \
  "$DOMAIN_FOUNDRY_HOME" "$DEMO_DF_BIN"
```

`setup --provider none -y --no-probe` is intentional: it initializes the
workspace without probing a provider. `setup --show` is the explicit receipt:
it should report `mode: heuristic`, no resolved API key, and a workspace path
under the fresh temporary home. Do not show a key, a probe, or a fabricated
successful live call.

When `DEMO_DF_BIN` points at this checkout's virtualenv, rebuild/stage the SPA
before filming the browser beats. The ignored `app/dist` can lag the source
tree; CLI/API success is not visual evidence for a stale bundle.

Choose exactly one activation source for the run.

### A. Installed synthetic pack (recommended recording path)

```bash
"$DEMO_DF_BIN" pack add "$DEMO_PACK_SOURCE"
"$DEMO_DF_BIN" pack validate sourdough
```

Expected installation receipt: JSON naming `sourdough`, its version, and its
workspace pack path; validation prints `OK`. This is an installed domain, so it
is a valid activation starting point without pretending that a model designed
it during the recording.

### B. No-key generated-domain fallback (scaffold)

Start again with a new temporary home, then run this instead of A:

```bash
export DOMAIN_FOUNDRY_HOME="$(mktemp -d)"
export DOMAIN_FOUNDRY_LLM=heuristic
unset DOMAIN_FOUNDRY_PACKS_PATH

"$DEMO_DF_BIN" setup --provider none -y --no-probe
"$DEMO_DF_BIN" new-domain "track my sourdough sessions" \
  --reply skip \
  --reply "baked a 75 percent hydration country loaf yesterday" \
  --reply "the loaf was dense" \
  --reply "the crust was crisp" \
  --reply "my starter is active" \
  --reply "fed the starter this morning" \
  --reply done
```

If this command exits non-zero, preserve the error and stop the scaffold beat;
do not narrate a generated domain as ready. Use this branch only when the
artifact emits the receipts described below; a green command alone still does
not make the scaffold `live`.

Expected wizard receipts include:

- an interview turn with a persisted `session_id`;
- a test-drive turn that says the domain is **scaffolded** and distinguishes
  its generated-example self-test from a guarantee about user language;
- one receipt per sample with a routing status (`applied` or safely `unfiled`);
- a final `done: true` turn saying the domain is ready for tracking.

If a sample is `unfiled`, keep that result on screen. The current UI wording is
“Saved — I wasn't sure where this belongs” with the Inbox repair affordance;
the CLI says it was safely stored. Do not edit a receipt or re-record it as
applied. The scaffold path is a fallback, not evidence of a held-out score or
a `live` domain.

## Server preflight

Start the daemon in a second terminal. Keep the first terminal available for
the restart and export beats.

```bash
"$DEMO_DF_BIN" serve --host 127.0.0.1 --port 8787
```

Open <http://127.0.0.1:8787>. If the page does not load from the exact artifact
under test, stop. Do not replace it with a screenshot from another run.

Before recording the final beat, check whether the artifact actually ships the
canonical-data export required by Slice 1 Gate 1. Prefer the CLI when it is
present; the current checkout's local HTTP endpoint is the fallback:

```bash
if "$DEMO_DF_BIN" export --help >/dev/null 2>&1; then
  echo "canonical export surface: CLI"
elif curl -fsS 'http://127.0.0.1:8787/api/export?domain=sourdough' >/dev/null; then
  echo "canonical export surface: local HTTP"
else
  echo "STOP: this artifact has no usable canonical-data export." >&2
fi
```

On the current checkout the CLI branch is the preferred path and the local HTTP
branch remains available as a read-only fallback. Both surfaces must be
verified against the exact artifact being recorded.

## 90-second recording beats

Use path A or path B above; the capture/correct/restart text is the same. The
terminal commands are also the copy-pasteable verification path when a browser
recording is not being made.

| Time | Surface and action | Expected visible receipt / caption |
|---|---|---|
| 0–8 s | Browser: **Your passions** at `127.0.0.1:8787`; show the installed Sourdough card, then open it. | “A fresh local workspace with one synthetic passion.” Do not call this a live model-designed domain. |
| 8–22 s | Domain Composer in **Log** mode: enter `baked a 75% hydration country loaf, came out great` and press **Save**. | The receipt headline is **Saved to Sourdough Journey as a bake**. The CLI shape is `status: applied` plus a routed `sourdough` / `bake` / `create` span. |
| 22–32 s | Leave the Composer result visible, then show the first timeline/bake view. | The new bake row is visible with its parsed fields. The view is useful even though the data is synthetic. |
| 32–43 s | Composer → **Ask** → `when did I last bake?`; click the citation chip if it is available. | With no key, the honest receipt is **Search-only mode (no model configured)** plus a citation that opens the saved object. A live-model cost line is conditional, not part of this run. |
| 43–57 s | Detail → **Correct** → change Hydration from `75` to `80` → **Apply correction**. | The correction applies through the same correction surface. Reloaded detail shows the actual revision, including `hydration: 75 → 80`; do not narrate a revision number unless it is visible. |
| 57–67 s | Stop the daemon with Ctrl-C. Start the same command again. Refresh the browser. | The same domain, row, and corrected value return. Caption: “A new process reopened the same local SQLite workspace.” |
| 67–83 s | Terminal: run the canonical export command or local HTTP fallback below, then inspect the written JSON. | A secrets-free `domain-foundry-export/1` payload contains the corrected hydration and a count for the bake. |
| 83–90 s | Browser: return to the domain view or Home. | End card: “Captured first. Correctable. Still local.” Keep the human-gate status out of the end card. |

## Copy-pasteable receipts

Use these commands to produce the receipts; do not paste the example IDs below
into a recording. The assertions check invariants rather than unstable IDs.

### Capture

```bash
CAPTURE_TEXT='baked a 75% hydration country loaf, came out great'
"$DEMO_DF_BIN" capture "$CAPTURE_TEXT" | tee "$DOMAIN_FOUNDRY_HOME/capture-receipt.json"
```

The receipt should contain:

```text
status: applied
routed: domain=sourdough, object_type=bake, operation=create,
        disposition=auto_apply, confidence=<number>
idempotent_replay: false
summary: the exact capture text
```

`projection_status` may be `pending` while the local projection loop catches
up. That is not permission to claim the projection is green; use the visible
domain row and the detail provenance as the evidence for this beat.

### Ask (no-key path)

The browser Composer's **Ask** mode is read-only. With the pre-roll above it
uses local search, not a model call:

```bash
curl -fsS -X POST 'http://127.0.0.1:8787/api/ask' \
  -H 'content-type: application/json' \
  --data '{"question":"when did I last bake?","domain":"sourdough"}' \
  | tee "$DOMAIN_FOUNDRY_HOME/ask-receipt.json"
```

Expected no-key invariants are `mode: search_only`, a non-empty `citations`
array, and no model-cost claim. The browser wording is **Search-only mode (no
model configured)**. A live-model answer and its cost line are a separate
provider-backed run and must only be recorded when they are visible.

### Correction

Use the parser-compatible, copy-pasteable correction text from the Slice 1
journey:

```bash
CORRECTION_TEXT='actually the hydration was 80 not 75'
"$DEMO_DF_BIN" correct "$CORRECTION_TEXT" | tee "$DOMAIN_FOUNDRY_HOME/correction-receipt.json"
```

Expected receipt invariants:

```text
action: amend
applied: true
details.fields.hydration: 80
error: null
```

The `entry_id`, `object_uid`, correction/event IDs, change-request ID, eval-case
ID, revision, timestamps, and projection status are dynamic. If `applied` is
false, keep the error visible and do not describe the correction as successful.

### Restart

After the browser restart beat, the CLI read surface is a useful secondary
check:

```bash
"$DEMO_DF_BIN" query --domain sourdough
"$DEMO_DF_BIN" health
```

The query should still return the capture entry. Health should be reported as
it actually returns; it is not a substitute for showing the corrected object.

### Canonical data export (Slice 1 Gate 1 prerequisite)

Use the CLI when it exists; otherwise use the current local HTTP surface. Both
write the same canonical-data shape to `export.json`:

```bash
EXPORT_FILE="$DOMAIN_FOUNDRY_HOME/export.json"
if "$DEMO_DF_BIN" export --help >/dev/null 2>&1; then
  "$DEMO_DF_BIN" export --domain sourdough --out "$EXPORT_FILE"
else
  curl -fsS 'http://127.0.0.1:8787/api/export?domain=sourdough' > "$EXPORT_FILE"
  echo "wrote $EXPORT_FILE via GET /api/export"
fi

python3 - "$EXPORT_FILE" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["format"] == "domain-foundry-export/1"
bakes = payload["domains"]["sourdough"]["objects"]["bake"]
assert bakes, "canonical export contains no bakes"
assert any(float(row["fields"].get("hydration") or 0) == 80.0 for row in bakes)
print("canonical export verified: corrected hydration=80")
PY
```

With the CLI `--out` form, the expected CLI receipt is a small JSON object
containing `wrote` and `counts`; `GET /api/export` returns the raw canonical
JSON when the HTTP surface is used. In both cases the file must contain the
format string above, the installed pack version, canonical objects, and the
corrected value; it must not contain API keys or other secrets. If neither
surface is available, or if the result exports eval cases instead of canonical
objects, stop the recording and report the missing prerequisite.

## Deliberately not claimed

This storyboard does not claim:

- that the human demo GIF gate has passed, that `docs/assets/demo.gif` exists,
  or that the README placeholder may be uncommented;
- that any live provider, model tier, model name, model price, or model-backed
  Ask answer was exercised; the default no-key path only claims a visible
  search-only citation when that receipt is actually present;
- that the current uncommitted source is the same as a built/released artifact,
  or that `build_release.sh`, the clean-machine gate, conformance, Playwright,
  or any other human gate has passed;
- that a human has completed the export/release gate; the storyboard only
  describes the CLI and HTTP surfaces when the exact artifact under test
  exposes them;
- that the scaffold self-test is a held-out acceptance score, that a scaffold is
  `live`, or that a repair loop passed;
- that synthetic captures are a founder/user validation run, a lived production
  week, or proof of the ten-minute test;
- that an `eval export` file is a portable dump of the user's canonical data;
- that a green local command or screenshot proves any other human gate.

## After a real recording

Only after a human has recorded the run against synthetic data:

```bash
python3 scripts/leakscan.py
```

Then follow [`LAUNCH_CHECKLIST.md`](../LAUNCH_CHECKLIST.md) §2. Do not create a
binary, un-comment the README image, or mark a gate complete from this text
artifact alone. The existing static walkthrough builder
[`scripts/build_walkthrough.py`](build_walkthrough.py) remains a separate
documentation artifact; its embedded screenshots are not evidence of this
recording.
