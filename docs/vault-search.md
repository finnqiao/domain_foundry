# Vault search conventions

Domain Foundry keeps **two** searchable surfaces. Use the right one.

## Ledger FTS (`domain-foundry search`)

Indexes:

- **entry** docs — `capture_event.raw_text` + entry summary (via sync triggers)
- **canonical** docs — flattened object field text written on apply

```bash
domain-foundry search "sake"
domain-foundry search "hydration" --domain sourdough --kind canonical
```

Python: `HarnessAPI.search(q, domain=..., object_type=..., kind=...)`.

Tokens are AND-matched. Prefer specific nouns over long phrases.

## Obsidian / markdown vault

Vault notes are projections, not the source of truth.

- Search the vault for human browsing; trust ledger FTS for agents and CLI.
- Managed regions (`%%managed:start … %%`) are rewritten on re-project — put free-text notes *outside* them.
- Backlinks: `[[entry:<entry_id>]]` and `%%uid:<object_uid>%%` resolve across notes after migration; prefer those ids over fragile note titles.
- Do not hand-edit managed body text expecting it to survive a drain — correct via `domain-foundry` / HarnessAPI so provenance stays intact.
