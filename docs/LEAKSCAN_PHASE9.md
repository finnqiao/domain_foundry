# Leakscan Phase 9 report

**Date:** 2026-07-23  
**Branch:** `feat/phase9-overlay-leakscan`  
**Base tip:** `dc8aa05`  
**Scope:** working-tree content heuristics + existing DB/binary/remote gates.  
**History:** **not rewritten** (plan absolute rule). Findings are fixed in the
working tree or documented; no `git filter-repo` / force-push.

## How to re-run

```bash
python scripts/leakscan.py
# optional private needles (never commit the file):
# DOMAIN_FOUNDRY_DENYLIST=~/HermesWorkspace/denylist.txt python scripts/leakscan.py
```

Exit non-zero on any finding. Reports print `path=` + `pattern=` only (no secret
material echoed).

## Patterns checked

| Pattern id | Heuristic |
|---|---|
| `personal_home_path` | `/Users/finn` |
| `email` | `local@domain.tld` (skips example/noreply/`git@github.com`) |
| `api_key_shape` | `sk-` / `sk-proj-` / `rk-` / `gh*_` / `AKIA…` / `xox*` |
| `telegram_bot_token` | `digits:token` bot-token shape |
| `telegram_id` | `telegram_*id` / `chat_id` assignments |
| (+ prior gates) | tracked `*.sqlite`/`*.db`, off-allowlist binaries, private remotes, optional denylist |

Intentional fixtures under `tests/` and `examples/synthetic/` are allowlisted so
sanitizer/redactor tests can plant fake secrets. The guard-the-guard unit test
plants a fake key **outside** those prefixes and asserts a non-zero scan.

## Working-tree results (this branch)

| Check | Count |
|---|---|
| Content / personal-string findings (after fixes) | **0** |
| Blocked tracked databases | **0** |
| Off-allowlist binaries | **0** |
| Forbidden remotes | **0** |
| **Total leakscan findings** | **0** |

### Findings fixed in-tree (path + pattern only; no secrets)

| Path | Pattern | Action |
|---|---|---|
| `docs/HANDOFF.md` | `personal_home_path` | Replaced absolute home paths with `/path/to/domain_foundry` |
| `docs/OPEN_SOURCE_HARNESS_PLAN.md` | `personal_home_path` | Rephrased private workspace as `~/HermesWorkspace` (private) |

No live API keys, Telegram bot tokens, or personal emails were present in
tracked non-allowlisted paths. Synthetic `sk-…` / email strings remain only
under allowlisted test/docs paths that exercise redaction.

## History note

```bash
python scripts/leakscan.py --history
```

Full-history string sweep is **advisory by default** (exit 0 when the working
tree is clean). Set `DOMAIN_FOUNDRY_LEAKSCAN_HISTORY_STRICT=1` to fail on
historical hits. The public repo already starts at the P0 bootstrap (see
[`LEAK_AUDIT.md`](LEAK_AUDIT.md)). Historical path hits (old HANDOFF absolute
paths; `sk-` shapes in redactor fixtures / CSS) are fixed **forward** in the
working tree — do **not** rewrite history.

## Overlay coupling

Personal packs belong under a private overlay (`DOMAIN_FOUNDRY_PACKS_PATH`, e.g.
`~/HermesWorkspace/packs/`) so they never enter this tree. See
[`PRIVATE_OVERLAY.md`](PRIVATE_OVERLAY.md).
