# Aquarium Water Journal

This application was compiled from `foundry-spec.json`. Its preview
and final local application are the same `app.html` artifact.

## Open

Open `app.html` directly in a modern browser. New records, immutable
prior versions, and receipts are stored in browser local storage.
**Export data** creates a complete JSON backup; **Restore backup**
validates the spec identity before replacing local state.

## Data model

`schema.sql` is SQLite DDL with identities, constraints, foreign
keys, relationship tables, and workload-derived indexes. Apply it
to a new database with foreign keys enabled.

## Ownership

- `foundry-spec.json` — complete product and derivation contract
- `evidence.json` — frozen source, principle, citation, and derivation snapshot
- `build-receipt.json` — artifact hashes and compiler identity
- `schema.sql` — executable local data model
- `app.html` — self-contained local application, correction history,
  and validated JSON export/restore

Generated output is MIT-licensed with Domain Foundry unless an
evidence or dependency record states otherwise. Reference-only
sources informed facts and patterns; their code and imagery are not
copied into this bundle.
