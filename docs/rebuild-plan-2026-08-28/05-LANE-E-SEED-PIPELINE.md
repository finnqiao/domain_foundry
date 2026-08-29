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

### 2026-08-28, E1 to E5 landed (uncommitted, integrator to commit)

**E1 readers.** `core/domain_foundry_core/seed/readers.py` plus `seed/models.py`.
One shape out of every source: `SeedRead` holding `SeedTable` rows and
`SeedDocument` pages, with `SeedProvenance` stamped at read time. Readers: xlsx,
csv/tsv, JSON/JSONL, mbox, notes folder (delegates to `ingest.iter_records`),
saved HTML, and a URL behind `--fetch`. **No new dependency was added.** The xlsx
reader is stdlib only: `zipfile` plus `xml.etree`, handling the shared string
table, inline strings, and the 1900 date serial. openpyxl was not added and is
not needed. Tests: `tests/unit/test_seed_readers.py`, 16 passed.

**E2 mapping inference.** `seed/mapping.py`. Roles are date, place, category,
quantity, free text, identifier, unmapped. The tidepool fixture maps exactly as
the story says, and the seven places and nine species come out as repeated lists.
The ambiguous fixture leaves three columns unmapped at confidence zero and says
so in the notes. The model call is optional, happens at most once, and is given
column names plus at most five sample rows; the model may only fill columns the
rules left open, never overrule them. Tests: `tests/unit/test_seed_mapping.py`,
14 passed.

**E3 preview and apply.** `seed/preview.py`, `seed/apply.py`, `cli_seed.py`.
`seed <path>` reads, infers, previews, and writes nothing. `--apply` is the only
write path, and it goes through `GenericImporter`, so ledger, provenance,
revisions, and corrections all hold. Applying twice writes zero the second time,
with a test on it. Every row's `source_ref` is `seed:<seed id>:<object>:<n>` on
channel `seed-personal` or `seed-public`, which is the row-level marking. Tests:
`tests/contract/test_seed_pipeline.py`, 20 passed.

**E4 seeds shape the schema.** `seed/brief.py`. `seed_brief_inputs(reads)` returns
`artifacts` (short lines for `FoundryPipeline.propose(artifacts=...)`) and `seeds`
(`list[SeedProvenance]` for `ResearchBrief.seeds`). The lines carry counts, column
names, date ranges, and how many values repeat, never the values themselves; there
is a test asserting her place and species names never appear. The seed ask ships
here as `SEED_ASK`, with `declined_seeding()` for the "just build" path. Tests:
`tests/unit/test_seed_brief.py`, 10 passed.

**E5 SP3 handshake.** The seed side is ready. Test counts for the whole lane:
60 passed. Regression check on neighbouring machinery: `test_importer.py`,
`test_capture_first.py`, `test_apply_corrections.py`, `test_ingest.py`,
`test_apply_engine.py`, `test_corrections_generalize.py`,
`test_correction_intent.py`, `test_contracts_2026_08_28.py`,
`test_foundry_pipeline.py`, `test_pack_lifecycle.py`: 77 passed. Lint clean
(`ruff check` and `ruff format`) on every file touched. The full suite was not
run, by instruction.

#### What Lane F should call for SP3

```python
from domain_foundry_core.seed import read_seed, seed_brief_inputs

reads = [
    read_seed("examples/seed-fixtures/tidepool-log.xlsx"),   # personal_upload
    read_seed("examples/seed-fixtures/field-guide.html"),    # public_link
]
inputs = seed_brief_inputs(reads)
# inputs.artifacts -> list[str], safe to pass to FoundryPipeline.propose(artifacts=...)
# inputs.seeds     -> list[SeedProvenance], goes on ResearchBrief.seeds
# inputs.summaries -> list[SeedSummary], row counts, repeated lists, date range
```

Guarantees Lane F can lean on:

- A personal upload has `kind="personal_upload"`, `shareable is False`, and
  `license is None`. It must never appear as a shareable source.
- A public link has `kind="public_link"`, a `location`, a `retrieved_at`, and
  `license="unknown until someone checks"`. That is the string research should
  show until a human reviews it.
- For traits detected off a seed, `TraitEdge(origin="detected", seed_ids=[...])`
  takes the ids from `inputs.seeds[i].id`.
- After `--apply`, `domain_foundry_core.seed.apply.seed_provenances(workspace)`
  returns every seed in a workspace without re-reading any file, and
  `load_seed_records(workspace)` adds the channel and the `source_ref` prefix for
  each one.

#### What Lane G should seed from

`examples/seed-fixtures/` (all committed, all regenerable with
`python examples/seed-fixtures/build_fixtures.py`, byte-stable):

| File | What it is |
|---|---|
| `tidepool-log.xlsx` | The acceptance fixture. 214 rows, columns `Date, Place, Species, Count, Notes`, 7 places, 9 species, 38 visits, dates 2024-04-05 to 2026-06-10. Dates are stored as real spreadsheet serials, notes as inline strings, places and species in the shared string table. |
| `tidepool-log.csv` | The same 214 rows, the sheets-export path. Reads identically, with a test pinning that. |
| `tidepool-observations.jsonl` | The same rows as another app's export, with an `id` column. |
| `tidepool-mail.mbox` | Six messages, for the mail path. |
| `tidepool-notes/` | Three markdown notes, for the folder path. |
| `field-guide.html` | The public page fixture: a rocky shore field guide, licence unknown. |
| `ambiguous.csv` | Four opaque columns, for the honest-gaps test. |

#### Cross-lane requests and things left undone

- **Integrator:** add `"cli_seed"` to `LANE_CLI_MODULES` in
  `core/domain_foundry_core/cli.py:2157`. That is the only line needed; the verb
  is tested through `register()` on a bare Typer app.
- **Integrator:** no `pyproject.toml` change is needed. Nothing was added.
- **Lane C:** `seed/preview.py` exposes `build_preview(...) -> SeedPreview` and
  `render_preview(preview, *, renderer=None) -> str`. A renderer is
  `Callable[[SeedPreview], str]`. Drop yours in at the `renderer` argument and
  nothing else in the seed pipeline changes. There is a test proving the swap.
  `seed/` does not import from `review/`.
- **Not done, needs another lane's file.** E4's second bullet, "the create ask
  offers seeding inline", could not be wired: the create flow lives in
  `wizard/` and `cli.py`, which this lane does not own. The copy and the decline
  check are ready as `domain_foundry_core.seed.brief.SEED_ASK` and
  `declined_seeding()`. Whoever owns the wizard turn should call those rather
  than writing the ask again.
- **A seed needs somewhere to land.** `--apply` writes into an existing pack, so
  `seed --apply` before the app exists fails with a plain message naming the fix.
  Seeding an app the same run that builds it is the create-flow wiring above.
