# Launch checklist

Everything the in-repo P9 work **prepared** but deliberately did **not execute**.
Finn runs these steps by hand. Nothing here is automated, published, or posted by
the build — do not assume any launch post is live.

Legend: ☐ = not started · ✅ = in-repo prepared / done · 🔒 = human/manual gate
(cannot be automated in-repo).

---

## 0. Name decision 🔒 (mostly done — availability still on you)

- ✅ Provisional public name: **Domain Foundry** — see
  [ADR-005](docs/adr/ADR-005-name-decision.md). Mechanical rename applied
  (`domain-foundry-core`, CLI `domain-foundry`, `~/.domain_foundry/`,
  `DOMAIN_FOUNDRY_*`, hermes entry-point `domain_foundry`, docs/README/mkdocs).
- ☐ Verify availability: PyPI (`domain-foundry-core`, `domain-foundry-hermes-agent`,
  `domain-foundry-pack-*` if needed), GitHub org `domain-foundry`, docs domain,
  trademark sanity check. Update placeholder GitHub URLs if the org differs.
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
scripts/release_audit.sh
```

This aggregates: leakscan · clock audit · no tracked DBs · git history starts at
P0 · ruff · full pytest · `mkdocs build` · eval corpus replay vs baseline. All
green as of this commit (see [`docs/LEAK_AUDIT.md`](docs/LEAK_AUDIT.md)).

- ☐ `scripts/release_audit.sh` green on the release commit.
- 🔒 External security pass on the API surface (independent reviewer) — see
  [`docs/security.md`](docs/security.md).
- 🔒 Founder-as-user-0 validation completed privately — see
  [`docs/FOUNDER_VALIDATION.md`](docs/FOUNDER_VALIDATION.md).

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

# 3. Build sdist + wheel.
python -m pip install --upgrade build twine
python -m build                      # writes dist/*.tar.gz + dist/*.whl

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
- 🔒 PyPI publish (core + adapter) and GitHub release/tag push.
- 🔒 Show HN / lobste.rs / Nous posts + awesome-list PRs.
- 🔒 External security pass on the API surface.
- 🔒 Founder-as-user-0 lived validation (private).
- 🔒 90-second demo GIF recording.
