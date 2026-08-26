# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (evidence-backed product foundry)

- A six-stage typed research → evidence → three concepts → domain model →
  experience → delivery pipeline that fails closed when credible vertical
  evidence is unavailable.
- Versioned `FoundrySpec`, three structurally distinct reviewed goldens, explicit
  remix lineage, workload-derived SQLite DDL, and a deterministic compiler whose
  preview is the exact self-contained owned application.
- A contract-interpreting owned runtime with typed chart, timeline, comparison,
  canvas, session, shelf, inspector, and workbench renderers; closed action
  semantics; immutable correction history; and validated spec-bound
  backup/restore with hostile-import browser coverage.
- Reviewed data-engineering, product/UX, and software-engineering knowledge
  corpus with source authority, license, allowed-use, freshness, principle, and
  derivation audits.
- First-party `/foundry` workbench, exact-app accessibility/reflow browser tests,
  real create-and-download export proofs for all three goldens, credential/input
  boundaries, generated-app CSP, atomic bundles, SPDX SBOM, vulnerability
  audits, held-out interests, and a Foundry threat model.
- Exact-candidate release evidence, seven fail-closed independent-review receipt
  contracts, a clean-candidate review-packet/sealing workflow, and a final
  public-release audit that binds reviews and their report hashes to a clean Git
  commit plus wheel/sdist/SBOM hashes.
- A cross-platform Python runtime license registry, production-only npm license
  policy, deterministic full-text third-party notices shipped in the web app,
  and a runtime-scoped SPDX SBOM with no unresolved license expressions.
- A dated official-source compatibility registry for every network provider;
  the release gate now fails when model defaults drift or the research is more
  than 30 days old.
- Time-bounded public-name evidence that records PyPI 404s without calling them
  reservations, detects repository-coordinate drift, and records that the
  `Domain-Foundry` GitHub organization is already occupied. It also records a
  live exact-mark US application with directly overlapping software services
  and prevents routine maintainer approval from silently clearing that risk.
- A primary-source remix landscape covering paid, community-first, and
  open-source AI builders, with explicit product implications for structural
  lineage, schema reasoning, ownership, and the scope Domain Foundry should not
  chase before its wedge is independently validated.

### Added (bring-your-own-key onboarding)

- **`domain-foundry setup`** — guided first-run flow: pick a provider, pick a
  model per tier, verify the key with one cheap live call per tier, then pick a
  starting point (ready-made pack / describe a log / pull in notes / attach a
  database). `--provider … -y` skips every question for expert installs, and
  `--show` prints what each setting resolved to and from where (keys redacted).
- **Provider registry** (`llm/providers.py`) — Anthropic, OpenAI, DeepSeek,
  OpenRouter, local/self-hosted, and an explicit offline choice, each with a
  suggested routine/sota pair. Suggestions only; the user overrides either tier.
- **Workspace config** (`~/.domain_foundry/config.toml`) — settings now resolve
  **env > config file > provider default**, so an env-var-only install is
  unchanged. The file records *which env var holds the key* by default;
  `--store-key` opts into writing it, and then the file is `chmod 0600`.
- **`domain-foundry import`** — exposes the mapping-driven importer that
  previously had no CLI: SQLite (`mode=ro`) and JSON/JSONL sources, `--table` /
  `--where` / `--order-by` remapping, dry-run by default, `--markdown`
  reconciliation, and a non-zero exit unless every source row is accounted for.

### Fixed

- Retired DeepSeek `deepseek-chat`/`deepseek-reasoner` defaults were replaced by
  the current `deepseek-v4-flash`/`deepseek-v4-pro` aliases. First-party OpenAI
  defaults now use GPT-5.6 Luna/Sol, and OpenAI-compatible request bodies are
  specialized for OpenAI and DeepSeek instead of assuming one shared parameter
  contract.

- **Anthropic requests sent `temperature`, which current models reject with HTTP
  400.** Because the router catches LLM failures into the keyword heuristic, this
  did not surface as an error — it looked identical to "no key configured". The
  request shape is now resolved per model (sampling params, `output_config.effort`,
  `max_tokens` headroom for models that think by default), with a minimal-body
  retry on 400 only. 401/429/5xx no longer retry, and errors are one readable line
  instead of an httpx MDN dump.
- **Completing setup changed nothing.** `get_default_provider` read only the
  `DOMAIN_FOUNDRY_LLM` env var, so a finished setup — key stored, probe green —
  still routed on keyword rules until the user separately exported
  `DOMAIN_FOUNDRY_LLM=live`. It now honours the config's `mode`.
- **`--home /elsewhere` ignored that workspace's config.** `Router` and the
  corrections service now thread their workspace home into provider construction.
- `TierSettings.configured` treated a *named but unset* env var as a working
  credential, so setup could report success with no reachable key.
- `DEFAULT_SOTA_MODEL` was stale (`claude-sonnet-4-6`); pricing table refreshed,
  and `tier_for_model` no longer assumes every Claude model is sota (Haiku is the
  suggested routine model).

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
