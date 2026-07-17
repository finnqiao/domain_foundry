# ADR-005: Product name

**Status:** Accepted (provisional)
**Date:** 2026-07-17

## Context

The public product name was undecided (plan §13.1). The previous in-repo working
name was `domain_expert` with PyPI `domain-expert-core` and CLI `domain-expert`.
Requirements for the final name: not "Hermes" (Nous collision), pronounceable,
PyPI + GitHub org + docs domain available, and it should evoke *structure for
the things you're passionate about*.

Candidates carried from planning: Trellis (previous front-runner), Loam,
Almanac, Fieldbook, Waypost, Lorebook, Tally — plus **Domain Foundry**.

## Decision

**Ship under Domain Foundry** as the provisional public product name.

| Surface | Value |
|---|---|
| Display name | Domain Foundry |
| Repo / directory | `domain_foundry` |
| PyPI core | `domain-foundry-core` |
| PyPI adapter | `domain-foundry-hermes-agent` |
| CLI | `domain-foundry` |
| Python packages | `domain_foundry_core`, `domain_foundry_hermes_agent` |
| Workspace | `~/.domain_foundry/` |
| Env prefix | `DOMAIN_FOUNDRY_*` |
| hermes entry-point | `domain_foundry` |
| GitHub (provisional; live under finnqiao until Domain Foundry org is owned) | `https://github.com/finnqiao/domain_foundry` |

Availability (PyPI / GitHub org / docs domain) and trademark sanity remain a
**human gate** before publish — see [`LAUNCH_CHECKLIST.md`](../../LAUNCH_CHECKLIST.md).
A later rename to a shorter brand (e.g. Trellis) is still mechanical if needed.

## Consequences

- Docs and code use `domain_foundry` / `domain-foundry` / **Domain Foundry**
  consistently.
- Launch drafts and mkdocs `site_name` use Domain Foundry.
- Because packs are data and adapters are HTTP clients, neither breaks on this
  rename beyond workspace-path and env-var prefix changes.
