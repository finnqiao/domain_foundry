# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (convergence finish)

- `packs/x_radar/` — signal/person pack + agent.yaml.
- SPA `quiz_stats` block + `GET /api/quiz/stats` (SRS aggregates).
- Food Inspiration timeline (`idea` / `noted_at`); capture-time place_name hints
  (`geo/capture_hints.py`, optional live geocode via env).
- Weekly Concierge triage nudge (`mesh weekly-triage`).
- Roamboard nightly shadow harness (`scripts/roamboard_shadow_nightly.sh`).
- Leakscan `--history` (advisory; no rewrite).
- Founder metrics script + mesh as-built / retirement / open-gates docs.

## [0.1.0] — unreleased (first public release)

The first public, open-source release. Local-first personal agent harness:
capture natural language → structured domain data → a remixable app.

### Added

- **Capture substrate & ledger** (P0–P1): append-only `capture_event`/`entry`,
  provenance chain, journal, revisions, two-database layout
  (`ledger.sqlite` + `domains.sqlite`), migration runner, ULID identity, MIT
  license, ADRs, CI + leakscan guardrails, `HarnessAPI`, FastAPI, CLI,
  attachments, contract tests.
- **Domain packs & hybrid routing** (P2): data-only six-file pack format, loader
  + compiler, L1 regex router + L2 LLM interpreter, cost guard, heuristic +
  cassette LLM providers, eval gate.
- **Apply & corrections** (P3): `ApplyEngine`, policy gates
  (auto_apply/review/confirm), canonical-change executor, one-message
  corrections with revision chains, correction → few-shot + `eval_case`.
- **Projections & review API** (P4): projection coordinator (outbox/drain/
  watermarks/retry), managed-region markdown vault, direct-query block data,
  enriched review queue with SLO counters.
- **Universal app shell** (P5): React + Vite SPA served from FastAPI; nine
  built-in blocks + registry; detail provenance; correction dialogs;
  side-loaded custom blocks.
- **Domain-creation wizard** (P6): goal → interview → generate → validate →
  dry-run → test-drive → harden; resumable sessions; `new-domain` CLI/HTTP.
- **Evaluation replay** (P7): cassette store (replay/record/live + drift
  report), frozen-clock audit, per-pack scorecards + committed baseline +
  regression diff, `eval backfill`/`eval export --sanitize`, PR + nightly CI
  gates, curated contract-case set, zero false-completed-actions (release
  blocking).
- **Reference packs & adapter** (P8): `food`, `travel`, `plants`, `sourdough`
  packs (data-only, synthetic fixtures); hermes-agent plugin
  (`register(ctx)` + `plugin.yaml` + `hermes_agent.plugins` entry point) with a
  live-stack conformance test; clean-machine quickstart gate.
- **Docs, audit & launch prep** (P9): MkDocs Material documentation site
  (concepts, architecture with data-flow diagram, adapter guide, security,
  gallery, remix tutorial); release-blocking leak audit + `release_audit.sh`;
  API bearer-token security contract test; launch artifacts (Show HN /
  lobste.rs / Nous drafts, awesome-list blurbs, issue templates); this
  changelog.

### Security

- Localhost binding by default; non-local bind refuses to start without a bearer
  token. Read-only, parameterized query paths; schema-validated identifiers;
  `safe_join` path safety; secret redaction before persistence. No telemetry.

### Notes

- The public product name is not yet finalized (see ADR-005); the distribution
  is published as `domain-foundry-core` for this pre-1.0 line.

[Unreleased]: https://github.com/finnqiao/domain_foundry/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/finnqiao/domain_foundry/releases/tag/v0.1.0
