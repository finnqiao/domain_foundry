# Release checklist, v0.1

Walk this top to bottom on the final tree. Every row green with evidence filled
in is what "release-ready" means. Publishing itself stays a human step, per
`LAUNCH_CHECKLIST.md` at the root of the repository.

One command runs everything that can be automated:

```
scripts/release_audit.sh --rebuild-gates
```

Status column: **green** means the command passes today. **red** means it fails
on purpose and the failure names what is missing. A red row is not a bug in the
gate; it is the gap, written down so it cannot be forgotten.

Last walked: not yet. Fill in the date and the evidence when you walk it.

## The five release proofs

| # | Proof | Command | Status | Evidence |
|---|---|---|---|---|
| 1 | The pipeline generates a showcase-caliber spec unaided | `python scripts/build_showcase.py --all --gate` | red: no cassettes | |
| 2 | Two apps for different passions are visibly, structurally different | `python scripts/foundry_difference_gate.py` | **green: 8 of 8** | run of 2026-08-28 |
| 3 | A real fork path end to end, parentage recorded | `python -m pytest tests/e2e-foundry/test_fork_e2e.py -q` | **green: 9 of 9** | run of 2026-08-28 |
| 4 | An out-of-corpus passion, seeded from a spreadsheet, yields an honest app | `python -m pytest tests/e2e-foundry/test_stranger_passion.py -q` | red: 2 of 6 checks, cassettes only | |
| 5 | README matches code: no dead fields, no ghost surfaces | `python scripts/claims_audit.py --strict-allowlist` | **green** | run of 2026-08-28 |

What each row stands at, after the lanes merged:

- **Proof 1.** Still red, and only for one reason: nothing has recorded a live
  pipeline run, which needs a key and a network. Record with
  `DOMAIN_FOUNDRY_LIVE_GATE=1 python scripts/build_showcase.py --all`, then
  commit `tests/e2e-foundry/cassettes/showcase/` and the generated bundles.
  The scorer, the thresholds and the replay refusal are in place and tested.
- **Proof 2.** Green, 8 of 8. Lane B's follow-up added `data-region-kind` to
  every rendered region and chose the rail element by topology, which moved the
  landmark count honestly rather than by padding. Measured on the two goldens:
  token distance 23.7, 53.3 percent of desktop pixels and 51.5 percent of phone
  pixels differ, axe clean, nothing scrolls sideways at 320px.
- **Proof 3.** Green, 9 of 9. `FoundryCompiler.render_readme` now names the
  parent when `remix.parent_spec` is set.
- **Proof 4.** The honesty floor is green: an out-of-corpus passion with no
  seeds and no consent stops with the three paths. Lane E's fixtures landed
  (`tidepool-log.xlsx`, 214 rows, and `field-guide.html`), so the only thing
  left is the same recorded live run as proof 1.
- **Proof 5.** Green. Run it with `--strict-allowlist`, which turns a stale
  allowlist entry into a failure instead of a note.

## The standing gates

All of these run inside `scripts/release_audit.sh`, with or without the flag.

| Gate | Command | Status | Evidence |
|---|---|---|---|
| leakscan | `python scripts/leakscan.py` | | |
| clock audit | `python scripts/clock_audit.py` | | |
| no tracked database files | inside `release_audit.sh` | | |
| git history starts at P0 | inside `release_audit.sh` | | |
| ruff | `ruff check core tests scripts adapters` | | |
| pyright | `pyright` | | |
| pytest | `python -m pytest -q` | | |
| mkdocs build | `mkdocs build --strict` | | |
| docs claims check | `python scripts/docs_claims_check.py` | | |
| knowledge audit | `python scripts/knowledge_audit.py` | | |
| dependency license audit | `python scripts/dependency_license_audit.py --verify-source-texts` | | |
| provider compatibility | `python scripts/provider_compatibility_audit.py` | | |
| name collision evidence | `python scripts/name_availability_audit.py` | | |
| foundry audit | `python scripts/foundry_audit.py` | | |
| foundry held-out | `python scripts/foundry_heldout_audit.py` | | |
| interest held-out leak check | `python scripts/heldout_leakcheck.py` | | |
| SPDX SBOM | `python scripts/generate_sbom.py` | | |
| Python vulnerability audit | `pip-audit --strict ...` | | |
| app dependency audit, lint, unit tests, build | `cd app && npm ...` | | |
| app browser E2E | `cd app && npx playwright test` | | |
| eval corpus replay | `domain-foundry eval --full --min-accuracy 0.9` | | |
| quickstart | `scripts/quickstart_gate.sh` | | |

## Live passes

Each model-facing gate runs on cassettes in CI. Before tagging, a person runs
each one live once and commits the receipt.

| Gate | Live command | Date | Receipt |
|---|---|---|---|
| Showcase | `DOMAIN_FOUNDRY_LIVE_GATE=1 python scripts/build_showcase.py --all --gate` | | |
| Stranger passion | `DOMAIN_FOUNDRY_LIVE_GATE=1 python -m pytest tests/e2e-foundry/test_stranger_passion.py -q` | | |

## Human gates

Unchanged, and each still blocks the public tag.

| Gate | Owner | Date | Evidence |
|---|---|---|---|
| Name clearance (ADR-005) | maintainer | | |
| External security review | maintainer | | |
| Demo recording: the "real June" run from the user story | maintainer | | |
| Screen-reader pass on a built app | maintainer | | |
| Package publication | maintainer | | |

## Notes for whoever walks this

- The rebuild gates are behind `--rebuild-gates` so a deliberately red gate
  cannot block the standing audit. Proofs 2, 3 and 5 are green; when the two
  cassette-blocked rows join them, delete the flag from
  `scripts/release_audit.sh` and run them always.
- The difference gate needs a browser: `cd app && npm ci && npx playwright
  install chromium`.
- `tests/e2e-foundry/` sits outside the configured `testpaths`, so a bare
  `pytest` does not collect it. Name the path, or run the audit with the flag.
  A `pytest_ignore_collect` hook in its own conftest enforces that. When every
  gate is green, delete that hook and add the directory to `testpaths` in
  `pyproject.toml`; doing it sooner would put a deliberately red gate into the
  standing suite.
