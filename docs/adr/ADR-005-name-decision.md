# ADR-005: Product name

**Status:** Provisional; public release blocked by exact-mark collision
**Date:** 2026-07-17

## Context

The public product name was undecided (plan §13.1). The previous in-repo working
name was `domain_expert` with PyPI `domain-expert-core` and CLI `domain-expert`.
Requirements for the final name: not "Hermes" (Nous collision), pronounceable,
usable distribution and repository coordinates, a suitable docs domain, and it
should evoke *structure for the things you're passionate about*.

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

The current preliminary registry evidence is in
`release/name-availability.yaml`: all
five PyPI JSON endpoints returned 404 on 2026-08-19, which means only “no public
project at check time,” while the `Domain-Foundry` GitHub organization is already
occupied and its ownership is unverified. More importantly, USPTO TSDR lists
live application `99880503` for the exact standard-character mark **DOMAIN
FOUNDRY**, filed by Semantic Foundry LLC for directly overlapping class-042
services including semantic/domain modeling, AI-assisted software development,
evidence-based code generation, and compiling domain models into deployable
artifacts. Public release under the provisional name is blocked until the
project renames, obtains a rights agreement, or receives qualified clearance.
Final coordinates, docs domain, and trademark disposition remain a **human
gate** before publish; see
`LAUNCH_CHECKLIST.md`. A later rename to a shorter
brand is still mechanical if needed. The 2026-08-20
[replacement-name slate](../name-replacement-slate.md) recommends
**Patternstead** after screening current registry, repository, domain, web, and
preliminary exact-mark evidence. That recommendation is not a final selection or
legal clearance.

## Consequences

- Docs and code use `domain_foundry` / `domain-foundry` / **Domain Foundry**
  consistently only as the current release-blocked working identity.
- Launch drafts and mkdocs `site_name` use Domain Foundry.
- Because packs are data and adapters are HTTP clients, neither breaks on this
  rename beyond workspace-path and env-var prefix changes.
- A rename before 0.1 should replace the entire public and technical identity;
  a display-only alias would leave the conflicting name in packages, CLI,
  repository, and artifacts.
