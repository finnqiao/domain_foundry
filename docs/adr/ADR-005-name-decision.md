# ADR-005: Product name (open)

**Status:** Proposed / **open decision** — deferred out of the P9 in-repo scope
**Date:** 2026-07-16

## Context

The public product name is still undecided (plan §13.1). The in-repo working
name is `domain_expert` (directory / repo) with the PyPI distribution
`domain-expert-core` and CLI `domain-expert`. Requirements for the final name:
not "Hermes" (Nous collision), pronounceable, PyPI + GitHub org + docs domain
available, and it should evoke *structure for the things you're passionate about*.

Candidates carried from planning: **Trellis** (front-runner — "structure your
passions grow on"), Loam, Almanac, Fieldbook, Waypost, Lorebook, Tally.

## Decision

**Defer.** P9 does **not** rename the package. Nothing in the code depends on the
marketing name: the CLI entry point, the distribution name, and the two SQLite
files are the only user-visible strings, and all are mechanical to change. A
rename is therefore a follow-up task, not a launch blocker for the in-repo work.

The final name decision, plus trademark + package-name availability checks, is a
**human launch gate** tracked in [`LAUNCH_CHECKLIST.md`](../../LAUNCH_CHECKLIST.md).

## Consequences

- Docs and code use `domain_expert` / `domain-expert` consistently today.
- When the name is chosen, the rename touches: repo/dir name, `pyproject.toml`
  (`name`, `[project.scripts]`, URLs), the CLI command string, the
  `~/.domain_expert/` workspace path, environment variable prefixes
  (`DOMAIN_EXPERT_*`), the `hermes_agent.plugins` entry-point label, and the docs
  `site_name`/`repo_url`.
- Because packs are data and adapters are HTTP clients, neither breaks on a
  rename beyond the workspace-path and env-var prefix changes.
