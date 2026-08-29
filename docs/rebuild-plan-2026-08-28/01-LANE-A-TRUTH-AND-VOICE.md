# Lane A: Truth and Voice (M0)

**Goal:** the repo tells the truth in plain words. Every claim maps to code, every dead surface is removed or labeled, and every user-facing string follows the copy rules in the overview. This lane also builds the audit that keeps it true for every later PR.

**Size:** S (days). **Start:** immediately after Phase 0. **Blocks:** release proof #5.

## Teardown evidence this lane answers

| Finding | Location (verified 2026-08-27; re-locate by content on drift) |
|---|---|
| `ImplementationSpec.targets` includes `standalone_react`, declared and read nowhere | `core/domain_foundry_core/foundry/models.py:425` |
| Studio claims "structurally different applications, not color variants"; measured difference is 9 hex values and one topology flag | `app/src/components/FoundryStudio.tsx:277` |
| SSE endpoint yields two frames and is called by nothing | `core/domain_foundry_core/api/app.py:960-974` |
| `VisualWorld` fields (`typography`, `density`, `layout_principle`, `signature_elements`, `avoid`) have zero readers | `foundry/models.py:295-306` vs `foundry/compiler.py`, `foundry/runtime.js` |
| Wizard `/create` is a message stack labeled "Your guide"; docs imply it is the flagship generator | `app/src/components/CreateDomain.tsx:242` |
| CLI copy is engineer-facing in places; asks are vague | `cli.py` prompt strings, `wizard/` turn copy |

## Files owned

`README.md` · `docs/` copy (not other kits' plan files) · copy strings in `FoundryStudio.tsx` and `CreateDomain.tsx` (strings only, no logic) · CLI prompt strings · `scripts/claims_audit.py` (new) · `tests/contract/test_claims_audit.py` (new) · `docs/COPY_RULES.md` (new)

## Phases

### A1: the claims audit (build the enforcement first)

- [ ] Write `scripts/claims_audit.py` with three checks: (1) **spec-field readers**: every field on `VisualWorld`, `ExperienceSpec`, and `ImplementationSpec` either has a reader in `compiler.py`/`runtime.js` or appears in an allowlist file `scripts/claims_audit_allowlist.yaml` with a "not yet: <lane>" reason; (2) **copy rules**: no em dash characters, no cost words ("free", "paid", "pricing", "upgrade") in user-facing strings and docs, allowlist for legitimate uses (LICENSE, third-party notices); (3) **claim map**: every README feature sentence carries a marker comment naming the test or script that proves it, checked for existence.
- [ ] Seed the allowlist honestly: `standalone_react` ("not yet: P1 WS8"), `VisualWorld` fields ("not yet: Lane B"), so the audit is green at birth and shrinks as lanes land.
- [ ] `tests/contract/test_claims_audit.py`: the audit runs clean on the current tree; a fixture with a violation fails.
- [ ] Ask the maintainer to wire the audit into CI (workflow files are hidden-path; do not edit them yourself). Until then, add it to `scripts/release_audit.sh`.
- [ ] Gate: `python scripts/claims_audit.py` exits 0; full suite green with exact counts.

### A2: dead surface removal

- [ ] `standalone_react`: keep the field, make selecting it a clear error ("Not available yet") at spec-load time, and record it in the allowlist. Removing the enum member breaks golden YAML round-trips; the error path is the honest middle.
- [ ] Delete the unused SSE endpoint at `api/app.py:960-974` and its route registration, or wire it to the create flow if Lane C requests it by SP2 (default: delete).
- [ ] Fix `FoundryStudio.tsx:277`: the "structurally different" line becomes true only when Lane B lands; until then it reads "Three different starting points" with no structural claim. After SP2, Lane A revisits and restores the stronger sentence if the difference gate is green.
- [ ] Gate: claims audit still green; suite green with counts.

### A3: the copy pass

- [ ] Write `docs/COPY_RULES.md`: the six copy rules from the overview, with three before/after examples each, including the pitch template ("Want to log every nudibranch you see? You already have a log of observations and dates. Build a Pokedex-style tracker for it.").
- [ ] Sweep every CLI question and status line: TLDR first, concrete asks, no jargon, no em dashes, no cost words. The seed ask names its inputs exactly ("a spreadsheet, a notes folder, photos, an export from another app or your email; one or two pages you trust, like a field guide or a species checklist").
- [ ] Sweep `README.md` and `docs/` user-facing pages with the same rules. Remove internal phase material from the public nav where it still leaks (check `mkdocs.yml` nav through the integrator).
- [ ] Label the `/create` wizard path for what it is until the P1 merge: a quick-capture starter, not the flagship generator. The foundry path is the release story.
- [ ] Gate: claims audit copy check green across the tree; suite green with counts.

### A4: README truth pass

- [ ] Rewrite README claims to match the post-lane reality only as lanes merge (coordinate at sync points; keep a "pending" branch of stronger claims that lands with SP2/SP3).
- [ ] Every remaining claim carries its proof marker.
- [ ] Gate: `python scripts/claims_audit.py` green on the final tree; this is release proof #5.

## Out of scope

Logic changes in the Studio or wizard (Lanes B, C, and the P1 merge). Workflow file edits without per-file approval. Anything in other lanes' owned files.

## Resume notes

(append here)

### 2026-08-28, A1: the claims audit

Landed `scripts/claims_audit.py`, `scripts/claims_audit_allowlist.yaml`,
`tests/contract/test_claims_audit.py`, and one line in
`scripts/release_audit.sh` (check 17). The audit has the three checks the phase
asked for and is green at birth.

- `python scripts/claims_audit.py` exits 0.
- `tests/contract/test_claims_audit.py`: all 24 tests green at A1.
- Ruff check and format clean on both new files.

How the checks work, and their honest limits:

- **fields**: a reader is a qualified access (`visual_world.density`,
  `world["density"]`, one level of local alias) inside `foundry/compiler.py` or
  `foundry/runtime.js`. It proves a field is used where the app is built, not
  that it changes a pixel. Lane G's difference gate is what proves that.
- **copy**: em dashes, cost words and prices, over a named list of
  user-facing pages plus the string literals of `cli.py` and the wizard
  modules. Docstrings count, because Typer turns a command docstring into its
  help text. A file on the list that does not exist yet is skipped, so a lane
  that has not landed cannot turn the audit red.
- **claims**: every list item under the README's `## What you get` carries
  `<!-- proof: <path> -->` and that path must exist; every item under
  `## Not true yet` carries `<!-- pending: <lane> -->`.

The allowlist is meant to shrink. Every entry needs a reason starting with
`not yet: `, `read by ` or `allowed: `, and the audit fails if an allowlisted
field gains a reader, so the entry cannot outlive the gap.

**For the maintainer, CI wiring.** Workflow files are hidden paths, so this was
not edited. Paste this step into the `ci` job of `.github/workflows/ci.yml`,
next to the existing `docs_claims_check` step:

```yaml
      - name: Claims audit
        run: python scripts/claims_audit.py
```

**Cross-lane requests:**

1. `scripts/docs_claims_check.py` is currently red on
   `docs/rebuild-plan-2026-08-28/06-LANE-F-BREADTH-AND-GRAPH.md:100`, which
   hardcodes an exact pytest count on that line. That is Lane F's plan doc and
   `docs_claims_check.py` is not a Lane A file. Either Lane F rewords the line,
   or the integrator adds `docs/rebuild-plan-2026-08-28/` to that script's
   `EXCLUDE_PREFIXES` the way the other plan kits are excluded.
2. `tests/contract/test_foundry_cli.py::test_foundry_validates_and_builds_an_owned_bundle`
   was failing on this shared tree at A1 time with
   `NameError: name '_resolve_experience' is not defined`, from an in-flight
   edit to `foundry/compiler.py` (Lane B). Not a Lane A change.
3. The wizard turn copy is allowlisted rather than swept. See the A3 note.

### 2026-08-28, A2: dead surface

- `standalone_react` stays in the model. `foundry/loader.py` gained
  `check_targets_are_buildable`, called from `load_foundry_spec`: a spec whose
  targets contain nothing buildable now stops with "This spec asks to be built
  as a standalone React app, which is not available yet. Change the target to
  foundry_runtime to build the app you own." The goldens list
  `[foundry_runtime, standalone_react]`, so they still load; the error is for a
  spec that names only the target nothing can build.
- The SSE endpoint `GET /api/create/{session_id}/events` is deleted from
  `api/app.py`, with its now-unused `StreamingResponse` import. Nothing in the
  app or the CLI opened it. `tests/contract/test_creation_release.py` asserted
  it, so that assertion was replaced with an inline-progress check and the test
  renamed to `test_release_api_supports_resume_and_cancel`.
- `FoundryStudio.tsx:277` no longer claims "structurally different
  applications, not color variants". It now reads "Three different starting
  points, each already built and reviewed." **After SP2, if Lane G's difference
  gate is green, Lane A restores a stronger sentence.** Two kicker lines and one
  `CreateDomain.tsx` error string lost their em dashes at the same time.
- `foundry/loader.py`, `api/app.py` and `tests/contract/test_creation_release.py`
  are not on any lane's owned list. The edits are the ones phase A2 names, and
  they are small. Flagging them so the integrator can see them.

Counts at A2: all 27 tests in `tests/contract/test_claims_audit.py` green; all
36 in `test_creation_release.py`, `test_foundry_spec.py`, `test_api.py`,
`test_app_shell.py` and `test_spa_packaging.py` green. Claims audit exits 0.

### 2026-08-28, A3: the copy pass

- New `docs/COPY_RULES.md`: the six rules, three before/after examples each, the
  pitch template, and the canonical seed ask verbatim for Lane E to use:
  "Point me at anything you already keep: a spreadsheet, a notes folder, photos,
  an export from another app or your email. If you have one or two pages you
  trust, like a field guide or a species checklist, those help too."
- Swept clean of em dashes, money words and prices: `README.md`,
  `docs/index.md`, `docs/gallery.md`, `docs/QUICKSTART.md`, all seven
  `docs/concepts/*.md` pages the audit scans, and all five
  `docs/tutorial/*.md` pages. Roughly 190 em dashes gone, each replaced by a
  full stop, a comma or a colon rather than by a rewrite, so nothing changed
  meaning.
- `docs/tutorial/howto-technical.md` also lost "cheapest per capture" and the
  `$0.25` figure. The setting it documents is still documented:
  "A daily guard caps model spend (`DOMAIN_FOUNDRY_DAILY_COST_CAP`, default
  `0.25`)."
- `cli.py`: 16 prompt, help and status strings swept. Note one deliberate
  divergence: `cli.py` now prints ", closest to what you described" where
  `wizard/release.py` still rewrites "(suggested)" into the em dash version. The
  wizard side is part of the sweep the integrator still owes.
- `CreateDomain.tsx` header now says what the `/create` path actually is: "Start
  something quickly", "A quick way to get a place to log things. Name a topic
  and answer a few questions. For the full build, with research and three
  concepts to choose from, use the foundry."
- The copy allowlist is down to `docs/COPY_RULES.md` (permanent: a page about
  banned words has to print them) plus the ten wizard modules.

**For the integrator, `mkdocs.yml` (integrator-only, so not edited):**

1. Add `- Copy rules: COPY_RULES.md` under the `Contribute` section.
2. Three internal records still sit in the public `Concepts` nav and should move
   out of it: `FOUNDRY_REDESIGN.md` (a gap-remediation record),
   `create-path-bar.md` (an internal comparison bar) and
   `name-replacement-slate.md` (a naming worksheet). They read as project
   history, not as things a user needs.

### 2026-08-28, A4: README truth pass

- `## What you get` is rewritten in plain words, six claims, each carrying a
  `<!-- proof: ... -->` marker that names a file the audit checks exists:
  `test_foundry_research_retrieval.py`, `test_foundry_pipeline.py`,
  `test_foundry_spec.py`, `scripts/foundry_audit.py`, `test_export.py`,
  `scripts/release_audit.sh`.
- New `## Not true yet` section, six entries, each with a
  `<!-- pending: <lane> -->` marker: the difference between two generated apps
  (Lane B and G), seeding an app from records you keep (Lane E), the review loop
  (Lane C), pack composition (Lane D), breadth and the trait graph (Lane F), and
  fork (Lane G). **The integrator promotes a line from pending to claimed at the
  sync point where its lane merges**, moving it up and swapping its `pending`
  marker for a `proof` marker. The audit fails if a promoted line has no proof.
- The opening blurb no longer says "researches the real practice, compares three
  materially different product concepts, derives a schema from the questions it
  must answer, and compiles the chosen experience". It says what happens.

Gate at A4: `python scripts/claims_audit.py --strict-allowlist` exits 0, with an
empty copy allowlist except the rules page and the wizard modules. This is
release proof #5, as far as Lane A can carry it: the remaining risk is that a
lane lands a stronger README line without a proof marker, which the audit
catches.

### Open items and cross-lane requests, end of Lane A

1. **`scripts/docs_claims_check.py` is red, and it is a release gate.** It now
   reports 14 failures, all of them exact pytest counts inside the resume notes
   of this plan kit (Lanes A, D, E and F all wrote them, as instructed).
   `docs/build-plan-2026-08/` is already on that script's `EXCLUDE_PREFIXES`;
   `docs/rebuild-plan-2026-08-28/` needs the same line. That script is not a
   Lane A file, so this was not done here.
2. **`tests/contract/test_creation_release.py::test_release_does_not_call_an_unfiled_first_note_ready`
   is failing on the shared tree**, raising `GenericFallbackRefused` from
   `wizard/blueprint.py:539`. That is Lane F's fallback work in flight, not a
   Lane A change. It passed before Lane F touched blueprint.py.
3. **`ruff format --check` is dirty on `core/domain_foundry_core/cli.py` and
   `core/domain_foundry_core/api/app.py`**, on lines Lane A did not write. Lane A
   deliberately did not run `ruff format` on either file, because that would
   reformat another lane's in-flight lines. Whoever owns those lines should run
   it.
4. **The wizard turn copy is still unswept**, and is the largest remaining voice
   gap: about 75 em dashes across ten modules. It needs Lane C (owns
   `wizard/looks.py`) and Lane F (owns `wizard/blueprint.py`), and it has to
   move `wizard/release.py`'s copy-contract patterns and several wizard tests in
   the same commit, or the suite goes red. Delete the `copy_files` entries as
   each module is swept.
5. **After SP2**, if Lane G's difference gate is green, restore a stronger
   sentence at `FoundryStudio.tsx:277` and promote the first `Not true yet`
   entry in the README.
6. **Run `python scripts/claims_audit.py --strict-allowlist` at every sync
   point.** The plain run only prints stale allowlist entries as notes, so that
   a lane landing a reader cannot turn the audit red for the other six agents.
   The strict run makes them failures, and is the one to use before a release.
