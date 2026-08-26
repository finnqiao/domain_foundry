# Launch checklist

Everything the in-repo P9 work **prepared** but deliberately did **not execute**.
Finn runs these steps by hand. Nothing here is automated, published, or posted by
the build — do not assume any launch post is live.

Legend: ☐ = not started · ✅ = in-repo prepared / done · 🔒 = human/manual gate
(cannot be automated in-repo).

---

## 0. Name decision 🔒 (provisional — exact-mark collision blocks release)

- ✅ A screened [replacement-name slate](docs/name-replacement-slate.md) now
  recommends **Patternstead** and documents two alternatives, rejected
  collisions, registry limitations, and the full pre-0.1 rename blast radius.
  This is a recommendation, not the maintainer's selection or legal clearance.
- ☐ Maintainer selects the final public stem before external reviewers sign the
  candidate. A rename invalidates candidate hashes and every receipt.

- ✅ Provisional public name: **Domain Foundry** — see
  [ADR-005](docs/adr/ADR-005-name-decision.md). Mechanical rename applied
  (`domain-foundry-core`, CLI `domain-foundry`, `~/.domain_foundry/`,
  `DOMAIN_FOUNDRY_*`, hermes entry-point `domain_foundry`, docs/README/mkdocs).
- ✅ **PyPI public-project check repeated 2026-08-19 — all five JSON endpoints
  return 404:**
  `domain-foundry`, `domain-foundry-core`, `domain-foundry-mcp`,
  `domain-foundry-telegram`, `domain-foundry-hermes-agent` (each returns 404 on
  `pypi.org/pypi/<name>/json`). This proves only that no public project exists at
  check time. It neither reserves a name nor guarantees PyPI will accept an
  upload. The seven-day evidence and its limitations are recorded in
  [`release/name-availability.yaml`](release/name-availability.yaml).
- ☐ **Claim them.** Distributions are built and verified (`dist/`, `twine check`
  PASSED, wheel contains the SPA + all eight reference packs). Needs a PyPI API
  token, which was not present in the build environment:
  ```bash
  # already done: npm run build && scripts/stage_webapp.sh && python -m build
  python -m twine upload --repository testpypi dist/*   # smoke-test first
  python -m twine upload dist/*                          # then for real
  ```
  Uploading a version is **irreversible** — PyPI will not let you re-use
  `0.1.0`. Confirm the name is the one you want (ADR-005 still calls it
  provisional) before the second command.
- ⚠️ GitHub organization `Domain-Foundry` is already occupied (created 2013,
  ownership unverified, zero public repositories at the 2026-08-19 check). Do
  not plan to claim it without a verified transfer. The current public repository
  is `finnqiao/domain_foundry`.
- ⛔ **Material exact-mark collision:** USPTO TSDR lists live application
  `99880503` for the standard-character mark **DOMAIN FOUNDRY**, filed by
  Semantic Foundry LLC on 2026-06-11 in class 042. Its stated services include
  semantic/domain modeling, AI-assisted software development, evidence-based
  code generation, and compiling domain models into deployable software
  artifacts. That directly overlaps this project. Publication under the current
  name requires a rename, documented rights agreement, or qualified legal
  clearance; a maintainer “sanity check” alone cannot clear the gate. This is
  preliminary risk evidence, not legal advice.
- ☐ Maintainer approves the final repository coordinate, docs domain, and
  trademark sanity check. Update placeholder URLs if the repository moves.
- ☐ Confirm `scripts/release_audit.sh` green on the rename commit (agent re-runs
  this; you confirm before publish).

## 0b. OSS uplift (Phase 9 overlay + leakscan) ✅ in-repo

- ✅ **Private overlay mechanism** — multi-dir
  `DOMAIN_FOUNDRY_PACKS_PATH` + `domain_foundry.packs` entry points; docs in
  [`docs/PRIVATE_OVERLAY.md`](docs/PRIVATE_OVERLAY.md). Personal packs can live
  at e.g. `~/HermesWorkspace/packs/` with no OSS repo diff.
- ✅ **Leakscan personal-string heuristics** —
  `scripts/leakscan.py` (home paths, emails, Telegram token/id shapes, API-key
  shapes); fixture test plants a fake secret; report in
  [`docs/LEAKSCAN_PHASE9.md`](docs/LEAKSCAN_PHASE9.md). **No git-history rewrite.**
- ☐ Move personalized packs into the private overlay location on the founder
  machine (OSS keeps genericized demos only).
- ☐ Founder-validation **measured results** table filled after a production week
  — stub in [`docs/FOUNDER_VALIDATION.md`](docs/FOUNDER_VALIDATION.md).
- ☐ One full single-stack **production week** (human gate; not claimed done).

## 1. Pre-flight (in-repo — already green) ✅ prepared

Run and confirm before anything ships:

```bash
scripts/candidate_gate.sh
python scripts/review_packet.py prepare
# complete reports and receipts with the named human reviewers
python scripts/review_packet.py seal
python scripts/public_release_audit.py
```

This aggregates code quality and typing, the full Python and browser suites,
documentation claims/builds, knowledge and Foundry/held-out audits, SPDX and
locked dependency vulnerability evidence, a production app build, hermetic
initialization, and eval-corpus replay. All are green in the current candidate
(see [`docs/LEAK_AUDIT.md`](docs/LEAK_AUDIT.md)).

- ✅ `scripts/release_audit.sh` **aggregate PASS** on the current candidate —
  including `pyright`, which it previously omitted.
- ✅ **Pyright debt cleared (was 45 errors / red since 2026-07-17).** Fixing it
  surfaced three things the red badge was hiding: Pyright runs *before* pytest in
  the workflow, so **the suite had not run in CI for twelve days**; the adapter
  E2E proofs under `adapters/*/tests/` were outside `testpaths` and so **gated
  nothing** (now collected — 281 → 288 tests); and one **real latent bug** —
  `capture_hints.py` called `NominatimClient()` without its required cache, so
  capture-time geocoding raised `TypeError` inside a bare `except` and silently
  never ran. Fixed with regression tests.
- ✅ `pyright` is a blocking step in `release_audit.sh`, and `pyright.extraPaths`
  / `pytest.pythonpath` / CI's `ruff` invocation now agree on the in-repo
  adapters. The local gate can no longer be weaker than the merge gate.
- 🔒 External security pass on the API surface (independent reviewer) — see
  [`docs/security.md`](docs/security.md).
- 🔒 Independent editorial review of the initial source registry and principle
  slate; `approved` means compiler-eligible, not independently endorsed.
- 🔒 Independent review of source/dependency licensing, generated-output
  boundaries, the runtime SBOM, and bundled third-party notices.
- 🔒 Founder-as-user-0 validation completed privately — see
  [`docs/FOUNDER_VALIDATION.md`](docs/FOUNDER_VALIDATION.md).
- 🔒 **One live `setup` probe per provider you intend to document.** The
  Anthropic request shape (which models reject `temperature`, which accept
  `output_config.effort`) is encoded from the published API contract and covered
  by unit tests against a mocked transport — but it has **not** been executed
  against a real key, because no credential was available in the build
  environment. A wrong entry in that table is a 400 that the router swallows into
  keyword routing, i.e. invisible. The probe is the check, and it takes seconds:

  ```bash
  ANTHROPIC_API_KEY=... domain-foundry setup --provider anthropic -y --probe
  # expect: routine claude-haiku-4-5 ok / sota claude-opus-5 ok
  ```

  Verified so far: a **bad** key correctly reports `HTTP 401: invalid x-api-key`
  on both tiers (so the failure path and the transport are real). The success
  path is unproven.

The exact scopes and fail-closed receipt templates for all human gates are in
[`docs/release-review-guide.md`](docs/release-review-guide.md) and
`release/templates/`. `public_release_audit.py` also requires that the receipt
commit, source-tree identity, wheel, sdist, and SBOM match the candidate manifest.

## 2. Demo GIF 🔒

- ☐ Record the 90-second walkthrough (capture → routing badge → app timeline →
  one-message correction) against **synthetic packs only**.
- ☐ Save to `docs/assets/demo.gif`; re-run leakscan; un-comment the README image.
- Do **not** fabricate a binary GIF; this is a genuine recording gate.

## 3. Tag & publish to PyPI (not executed) 🔒

Prereqs: a clean `release_audit.sh`, a chosen name, `build` + `twine` installed,
and a PyPI API token.

```bash
# 1. Bump/confirm version in pyproject.toml and CHANGELOG.md (move [0.1.0] out of "unreleased").
# 2. Tag.
git tag -a v0.1.0 -m "domain_foundry v0.1.0"

# 3. Build the SPA and stage it into the package, then build sdist + wheel.
#    Skipping the stage step ships a wheel with no web app: `domain-foundry serve`
#    returns JSON and the README quickstart's "then open 127.0.0.1:8787" is a lie.
( cd app && npm ci && npm run build )
scripts/stage_webapp.sh              # app/dist -> core/domain_foundry_core/_webapp
python -m pip install --upgrade build twine
python -m build                      # writes dist/*.tar.gz + dist/*.whl

# 3b. Verify the wheel actually contains the app and the reference packs.
python - <<'PY'
import glob, zipfile
names = zipfile.ZipFile(sorted(glob.glob("dist/*.whl"))[-1]).namelist()
assert any("_webapp/index.html" in n for n in names), "wheel has no SPA — run scripts/stage_webapp.sh"
assert any("_bundled/food/pack.yaml" in n for n in names), "wheel has no reference packs"
print("wheel contents OK")
PY

# 4. Smoke-test on TestPyPI first.
python -m twine upload --repository testpypi dist/*
pipx install --index-url https://test.pypi.org/simple/ domain-foundry-core

# 5. Publish for real.
python -m twine upload dist/*

# 6. Publish the adapter separately (its own pyproject under adapters/hermes_agent).
( cd adapters/hermes_agent && python -m build && python -m twine upload dist/* )

# 7. Verify.
pipx install domain-foundry-core && domain-foundry --help
```

- ☐ Push the tag: `git push origin v0.1.0`.
- ☐ Create the GitHub release; paste the `CHANGELOG.md` 0.1.0 section.
- ☐ (Optional) publish the docs site (e.g. `mkdocs gh-deploy`).

## 4. Launch posts (drafts prepared, not posted) 🔒

Drafts are under [`docs/launch/`](docs/launch/). Post in this order and keep the
first two hours clear for replies:

- ☐ **Show HN** — [`docs/launch/show-hn.md`](docs/launch/show-hn.md).
- ☐ **lobste.rs** — [`docs/launch/lobsters.md`](docs/launch/lobsters.md)
  (tags: `ai`, `databases`, `python`; mark `show`).
- ☐ **Nous community post** — [`docs/launch/nous.md`](docs/launch/nous.md).
- ☐ **awesome-list PRs** — blurbs in
  [`docs/launch/awesome-list-blurbs.md`](docs/launch/awesome-list-blurbs.md)
  (open the PRs by hand; do not auto-submit).

## 5. Post-launch triage

- ☐ Watch HN/lobste.rs threads for the first ~4 hours; reply fast and plainly.
- ☐ Triage inbound issues daily for the first week using the labels below.
- ☐ For every real routing miss, ask the reporter for (or synthesize) a
  **synthetic** repro and attach it as an `eval_case` — corrections/misroutes
  become permanent regression tests.
- ☐ Keep a running "friction log" and fold recurring gaps into the pack style
  guide / wizard prompts.

### Triage labels

| Label | Meaning | First action |
|---|---|---|
| `routing` | misroute / ambiguity | reproduce with a synthetic fixture; add to corpus |
| `fields` | extraction gap (unit/enum/date) | check schema `unit`/`allow_other`; add fixture |
| `corrections` | correction intent missed | add correction case; check few-shot bank |
| `wizard` | bad question / weak generated pack | tune archetype or style-guide prompt |
| `app` | block/view gap | config-level fix or custom-block guidance |
| `adapter` | hermes-agent capture-first friction | check SKILL.md guidance / version range |
| `pack-submission` | community pack | must pass `pack validate` + routing dry-run before listing |
| `security` | posture / disclosure | follow SECURITY.md; do not discuss exploit detail publicly |

### Triage severity

- **P0** — data loss, a false-completed-action in the wild, or a security issue →
  hotfix + patch release.
- **P1** — a broken quickstart step or a common misroute → fix within days.
- **P2** — polish, docs, nice-to-have packs → batch.

---

## Human gates summary (nothing below is done by the build)

Step-by-step handoff: [`docs/HANDOFF.md`](docs/HANDOFF.md).
Synthetic UI evidence: [`docs/assets/evidence/`](docs/assets/evidence/).

- 🔒 Name availability/trademark checks (provisional name **Domain Foundry** already applied).
- 🔒 Resolve the exact-mark collision by rename, rights agreement, or qualified
  clearance before approving any publication action.
- 🔒 PyPI publish (core + adapter) and GitHub release/tag push.
- 🔒 Show HN / lobste.rs / Nous posts + awesome-list PRs.
- 🔒 External security pass on the API surface.
- 🔒 Founder-as-user-0 lived validation (private).
- 🔒 90-second demo GIF recording.
