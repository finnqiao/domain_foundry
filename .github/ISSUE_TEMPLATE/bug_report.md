---
name: Bug report
about: Something is broken or behaves unexpectedly
title: "[bug] "
labels: [bug]
assignees: []
---

<!--
Use SYNTHETIC data only. Never paste real personal captures, notes, tokens, or
file paths. Translate any real example into an invented one before filing.
-->

## What happened

A clear, concise description of the bug.

## Expected behavior

What you expected instead.

## Reproduction (synthetic only)

Steps or commands, with invented capture text:

```bash
domain-foundry init
domain-foundry pack add packs/plants
domain-foundry capture "watered the monstera, soil still damp"
# ...
```

## Environment

- `domain_foundry` version / commit:
- Install method: `pipx` / `pip -e .` / other:
- OS + Python version:
- Adapter in use (if any): hermes-agent version / none

## Logs / output

<details>
<summary>Relevant output (redact anything personal)</summary>

```
paste here
```

</details>

## Checklist

- [ ] I used synthetic data only (no personal captures, secrets, or paths).
- [ ] I can reproduce this from a fresh `domain-foundry init`.
