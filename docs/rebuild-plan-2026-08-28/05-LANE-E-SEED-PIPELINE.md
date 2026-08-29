# Lane E: The Seed Pipeline (M3a)

**Goal:** one `seed` command takes what the user already keeps and turns it into the data backend they never have to think about. Spreadsheets, CSVs, note folders, other apps' exports, mail exports, and trusted public pages all land through the same verb, with an inferred mapping, a dry-run preview page, and apply-on-approval. Every app is born full, not empty. This is the hidden center of the product per the maintainer's notes, part of WS7 (P0).

**Size:** M to L (1.5 to 2 weeks). **Start:** after Phase 0, parallel with everything. **Meets Lane F at SP3** (seed provenance flows into research marking).

## What already exists (build on it, do not duplicate)

| Capability | Location |
|---|---|
| Free-text ingest of a notes folder, dry-run by default, watch mode | `domain-foundry ingest` (see `docs/tutorial/adopt-in-place.md`) |
| Structured import from SQLite and JSON/JSONL via a hand-written mapping YAML, read-only sources, idempotent, non-zero exit unless every row lands | `domain-foundry import -m mapping.yaml`, `examples/importers/` |
| Read-only source discipline (`mode=ro`, notes never moved) | import machinery |

The gap: no xlsx, no sheets or mail exports, mappings are hand-written, imports are not part of the create flow, and imported history does not shape the schema.

## Teardown and story evidence

| Finding | Location |
|---|---|
| The create ask is vague and the flow accepts no user data | wizard turn copy; `cli.py` create path |
| Importer mappings are hand-authored YAML, all pointed at travel/japanese/roamboard | `examples/importers/*.yaml` |
| The story's scene 2 is the acceptance script: 214-row xlsx, inferred mapping, preview, apply, "born full" | `June at Low Tide`, scene 2 |

## Files owned

`core/domain_foundry_core/seed/` (new package: readers, mapping inference, preview, provenance) · `core/domain_foundry_core/cli_seed.py` (new) · `examples/seed-fixtures/` (new: xlsx, csv, sheets export, mbox, notes folder, plus a public-page HTML fixture) · related tests

Shared: `SeedProvenance` type from Phase 0 (`personal_upload` vs `public_link`; personal is never shareable). The review-page renderer from Lane C's `review/` package is a consumer dependency; until C1 merges, emit a plain HTML table preview behind the same function signature.

## Design constraints

- Read-only sources, always. Dry-run by default; `--apply` is the only write path. Idempotent: re-running a seed adds nothing new.
- Every seeded record carries `SeedProvenance`. Personal uploads are marked personal at the row level; this marking is what the sharing line and Lane F depend on. Public pages are marked with URL, retrieval date, and license-unknown-until-reviewed.
- Mapping inference may use one model call (user's key) on column names and a small sample; full file contents are not sent. Say so in the command's one-line description.
- The ask copy is Lane A's concern but ships here first, following the rules: name exactly what helps ("a spreadsheet, a notes folder, photos, an export from another app or your email; one or two pages you trust, like a field guide or a species checklist").

## Phases

### E1: readers

- [ ] `seed/readers.py`: xlsx (openpyxl or a stdlib-friendly parser, integrator to approve the dependency), csv/tsv, Google Sheets export files (xlsx/csv as downloaded), JSON/JSONL (reuse import machinery), mbox mail export (subject, date, body as note candidates), notes folder (delegate to existing ingest), and a public URL or HTML file (readability extraction to a reference document, not records).
- [ ] Every reader emits the same intermediate shape: rows with typed cells plus source provenance.
- [ ] Tests: one fixture per reader in `examples/seed-fixtures/`; unreadable input fails with a plain message naming what was expected.
- [ ] Gate: suite green with counts.

### E2: mapping inference

- [ ] `seed/mapping.py`: infer column roles (date, place, category, quantity, free text, identifier) from headers, types, and a bounded sample; detect repeated values that should become their own lists (June's seven places, nine species). Output is a reviewable mapping (the same shape the existing `import` mapping YAML uses, extended), never silently applied.
- [ ] Confidence is honest: unmapped columns are listed as unmapped, not guessed into oblivion.
- [ ] Tests: the tidepool fixture (built to match the story: 214 rows, date/place/species/count/notes) maps as the story says; an ambiguous fixture yields explicit unmapped columns.
- [ ] Gate: suite green with counts.

### E3: preview and apply

- [ ] `seed/preview.py`: emit `seed-preview.html`: what was read, the inferred mapping in plain words ("I'll treat each row as one sighting during a visit"), sample rows placed into their target shape, unmapped columns, and the exact counts that will be written. Plain HTML table now; upgrade to Lane C's review renderer when C1 merges.
- [ ] `cli_seed.py`: `seed <path-or-url>` runs read plus infer plus preview; `seed --apply` writes through the existing capture/apply machinery so provenance, ledger, and corrections all hold; `seed --mapping <file>` accepts a hand-edited mapping.
- [ ] Idempotency test: apply twice, second run writes zero.
- [ ] Gate: suite green with counts.

### E4: seeds shape the schema

- [ ] Surface the seed summary (entities seen, repeated lists, date ranges, row counts) into the foundry brief as typed artifacts, so the research and domain stages design around real data. The pipeline already accepts artifacts on the brief; wire seeds in as first-class artifact entries with provenance.
- [ ] The create ask offers seeding inline (the story's scene 2 script) and continues without it on "just build".
- [ ] Tests: a brief with a seeded spreadsheet produces a domain stage input containing the seed summary; cassette-based.
- [ ] Gate: suite green with counts.

### E5: SP3 handshake with Lane F

- [ ] Provenance flows: seeded public links appear in research as user-supplied sources with their marking; personal uploads never appear as shareable sources. Integration test owned by Lane F; this phase makes the seed side ready.
- [ ] Gate: SP3 test green.

## Definition of done

June's scene 2 works verbatim against the tidepool fixture: seed the xlsx, read the preview, apply, seed the field-guide URL, and the on-file summary distinguishes her log, her guide, and model knowledge. The stranger-passion E2E (Lane G) can seed from a fixture and the resulting app opens with history inside.

## Out of scope

Live Google Sheets API or IMAP connections (exports only for v0.1). Schema evolution of already-built apps from later seeds (P2). The contribute loop (P1 WS11).

## Resume notes

(append here)
