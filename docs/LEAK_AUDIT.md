# Leak audit (release-blocking)

The private HermesWorkspace repo has personal SQLite databases and personal
notes in its git history. The absolute rule (plan §12.1) is therefore: **the
public repo starts empty and porting is re-typing/adapting, never
`git filter-repo`/subtree/shared-remote.** This page records the P9
release-blocking audit and how to re-run it.

## How to re-run

```bash
python scripts/leakscan.py        # tracked db/binaries, private remotes, optional denylist
python scripts/clock_audit.py     # no wall-clock outside the injectable clock provider
scripts/release_audit.sh          # aggregate gate (leakscan + clock + history + ruff + pytest + mkdocs + eval)
```

Set `DOMAIN_FOUNDRY_DENYLIST=/path/to/private/denylist.txt` to also scan every
tracked text file for private names/URLs. The denylist file itself is **never**
committed (plan §12.2).

Phase 9 also enables built-in personal-string heuristics (home paths, emails,
Telegram token/id shapes, API-key shapes) — see
[`LEAKSCAN_PHASE9.md`](LEAKSCAN_PHASE9.md) for the working-tree report (0 findings
after path scrub; history not rewritten).

## Results — P9 (2026-07-16, HEAD `7468e31` + P9 working tree)

| Check | Result |
|---|---|
| `leakscan.py` (tracked `*.sqlite`/`*.db`, binaries off-allowlist, private remotes) | **OK** |
| `clock_audit.py` (frozen-clock discipline) | **OK** |
| No tracked database files (`git ls-files | grep sqlite/db`) | **OK** — none |
| Git history first commit is the P0 bootstrap (no pre-P0 import) | **OK** — `Bootstrap domain_foundry P0/P1 substrate.` |
| `ruff check core tests scripts adapters` | **OK** |
| Full `pytest` | **OK** — 92 passed |
| `mkdocs build` | **OK** |
| Eval corpus replay vs committed baseline | **OK** — routing ≥0.9, 0 false-completed-actions |

### Manual review

- **Fixtures / examples are synthetic.** All routing fixtures and eval corpora
  under `examples/synthetic/` and `packs/**/evals/` use invented content. The
  `travel` pack deliberately uses synthetic place names ("Port City", "River
  Station", "Old Town") — no real locations copied.
- **Email/secret strings in tests are synthetic.** The only `@`-addresses in the
  tree (`a@b.com`, `bob@corp.io`) and secret-shaped tokens (`sk-…EXAMPLE`,
  `ghp_…`, `AKIA…EXAMPLE`) exist **only** to test the PII sanitizer and secret
  redactor. They are not real credentials.
- **The "finn"/"hermes"/"HermesWorkspace" strings** in the tree appear **only**
  inside `scripts/leakscan.py` and `scripts/check_remotes.sh` — i.e. they are the
  denylist patterns that *guard against* leaks, not leaked content.
- **No `/Users/<name>` home paths** are tracked.
- **Screenshots / demo GIF:** none are committed yet. The README reserves a
  placeholder; the demo GIF is a human recording gate (see
  [`LAUNCH_CHECKLIST.md`](https://github.com/finnqiao/domain_foundry/blob/main/LAUNCH_CHECKLIST.md)). Any future screenshot must be
  captured from synthetic packs only and re-audited before commit.
- **Reference architectures are described, not shipped.** The public plan
  (`docs/OPEN_SOURCE_HARNESS_PLAN.md`) names the private applications only as
  *described* design lineage; no private code, schema, or data was ported.

### Sign-off status

The **in-repo** portion of the audit is green and reproducible via
`scripts/release_audit.sh`. The **external security pass** on the API surface and
a final human sign-off remain launch gates (see `LAUNCH_CHECKLIST.md`).

## What stays private, forever

Personal data and vault; the private reference apps (they become *described*
architectures in docs, not shipped code); persona docs (the public repo ships
neutral templates); personal packs; and the PII denylist file itself.
