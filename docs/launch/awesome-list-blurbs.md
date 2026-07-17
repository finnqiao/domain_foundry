# Awesome-list PR blurbs (not submitted)

> Draft only. Finn opens each PR by hand at launch (see `LAUNCH_CHECKLIST.md`).
> Do **not** auto-submit. Match each list's exact formatting/contribution rules;
> keep entries one line, alphabetized where required, and swap in the final name
> + URL. Only submit to lists whose scope genuinely fits.

## Target lists

| List | Fit | Section |
|---|---|---|
| awesome-hermes-agent (core list) | plugin/adapter | Plugins / Integrations |
| awesome-hermes-agent (community/plugins list) | plugin/adapter | Data / Storage |
| awesome-local-first | local-first SQLite app | Tools / Apps |
| awesome-selfhosted (only if it fits their rules) | self-hostable local daemon | Personal data |

## One-line entries

**awesome-hermes-agent (plugins):**

```markdown
- [Domain Foundry](https://github.com/finnqiao/domain_foundry) — Local-first harness that turns agent-captured messages into structured, per-domain SQLite data via data-only "packs"; ships a `register(ctx)` plugin exposing capture/query/correct/review over HTTP.
```

**awesome-local-first:**

```markdown
- [Domain Foundry](https://github.com/finnqiao/domain_foundry) — Capture natural language, get a local-first structured app for any domain. Append-only SQLite ledger, offline-checkable YAML packs, one-message corrections, no telemetry. (MIT, Python)
```

**awesome-selfhosted (if in-scope):**

```markdown
- [Domain Foundry](https://github.com/finnqiao/domain_foundry) - Local-first personal data harness: describe a domain, capture in plain language, get structured SQLite + a small app. `MIT` `Python`
```

## PR description template

```markdown
### Adding: domain_foundry

A local-first personal agent harness (MIT, Python 3.11+). It turns
natural-language captures into structured, domain-specific SQLite data via
data-only "packs", with capture-first + never-drop invariants and a
hermes-agent plugin.

- Repo: <url>
- Docs: <docs url>
- License: MIT
- Active / maintained: yes (v0.1.0)

I believe it fits the **<section>** section because <one sentence>. Happy to
adjust wording/placement to match the list's conventions.
```

## Etiquette reminders

- Read each list's CONTRIBUTING before opening the PR; follow its ordering and
  punctuation exactly (some require a trailing period, some forbid it).
- One list per PR. Don't cross-post the same PR text verbatim.
- Don't add to a list whose scope you're stretching — a rejected PR for being
  off-topic is worse than not submitting.
