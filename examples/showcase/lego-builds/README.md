# LEGO Builds — Build Bench

**TARGET ARTIFACT** — the spec is hand-authored (Phase 0 bar); the bundle beside it is compiled from that spec by the real deterministic FoundryCompiler (`foundry build`), no live LLM involved. The live pipeline's acceptance test is producing a spec of this caliber unaided.

## The interest

A builder works through one set at a time, bag by numbered bag, over evenings that end mid-step — so the question that actually matters between sittings is "which bag am I on?", not "how many sets do I own". Half the shelf is official sets with a set number the whole world shares, and half is MOCs the builder designed themselves, which have a name and a designer and no set number at all. When a build finishes it goes somewhere — the display shelf, back in the box, or parted out into the bins — and along the way two tiles always turn out to be missing, which is a note that has to survive until an order is worth placing.

## Acceptance utterances

The finished pipeline's app must file both of these correctly, with no schema change and no free-text dumping ground:

- **"finished the Millennium Falcon MOC, 3800 pieces, missing 2 tiles"** — files as **two** records against **one** entity graph. A `build_project` with `origin: moc`, `title: Millennium Falcon`, `piece_count_claimed: 3800`, `status: built`, and `set_num` **left empty** — plus a `part_shortage` against that project with `element_kind: tile`, `quantity_missing: 2`, `status: open`. The trap is the name: the app must **not** bind this to canonical `lego_set` 75192, because the utterance says MOC and 3800 pieces while the official UCS Falcon is set 75192 at 7541 pieces. A MOC has no set number; inventing one would be a fabrication.
- **"sorted set 75192 into the parts bins, instructions in the binder"** — files as an **update** to the existing `build_project` whose `set_num` is `75192`: `status` transitions to `parted_out` (a declared transition on the project lifecycle, not a delete), `storage_slot_id` moves to the `parts_bin` slot, and `instructions_location` becomes the binder. It must match the **existing** canonical `lego_set` record for 75192 rather than creating a second one, and the build's sitting log and past shortages must survive the transition intact.

## Vocabulary bar

The generated app has to understand these as terms of art, not as generic strings:

| Term | What it must mean in the model |
| --- | --- |
| **MOC** | My Own Creation — a build with a designer and a claimed piece count and no set number. First-class, not a degenerate set. |
| **minifig** | A minifigure; counted on the official set (`minifig_count`) and a valid shortage family (`minifig_part`). |
| **set number** | The catalogue's canonical identity, e.g. `75192`. Shared across every owner's copy; never the identity of a builder's copy. |
| **pieces** | Piece count — the catalogue's for a set, the builder's own count for a MOC. Two different fields for a reason. |
| **studs** | The unit of shelf space. `footprint_studs` is how wide a finished build sits, not a decorative flourish. |
| **plates / tiles** | Element families with distinct part numbers; `element_kind` enumerates tile, plate, brick, slope, technic, minifig_part. |
| **theme** | The set's family — "Star Wars UCS", "Icons Space". The axis the shelf is browsed by. |
| **instructions** | A physical thing with a location: the booklet on the mat, the box, or a tab in the binder. It outlives the build. |
| **parting out** | Breaking a finished build back into sorted bins. A legal end state on the lifecycle, never a deletion. |
| **WIP** | Work in progress — the bench state, carrying the last bag and the step it stopped on. |
| **display shelf** | A named `storage_slot`, alongside parts bins, sealed stacks, and the instruction binder. |

## Files

| Path | What it is |
| --- | --- |
| `spec.yaml` | The hand-authored FoundrySpec — 5 entities, 4 relationships, 5 constraints, 4 indexes, 4 workloads, 1 state machine, 3 concepts, 4 views, 6 evaluation cases. This is the bar. |
| `bundle/foundry-spec.json` | The validated spec as the compiler read it. |
| `bundle/app.html` | Self-contained local app — four views, the Instruction Bench visual world, sample records, correction history, JSON export/restore. |
| `bundle/schema.sql` | SQLite DDL: identities, enum checks, foreign keys, the workload-derived indexes. Executes clean against a fresh database. |
| `bundle/evidence.json` | Frozen snapshot of the sources, principles, citations, and derivations behind the spec. |
| `bundle/build-receipt.json` | Artifact hashes, compiler identity, and the source and principle IDs used. |
| `bundle/README.md` | Compiler-generated ownership note that ships inside the bundle. |

Rebuild with:

```
domain-foundry foundry validate examples/showcase/lego-builds/spec.yaml
domain-foundry foundry build examples/showcase/lego-builds/spec.yaml --output examples/showcase/lego-builds/bundle
```

`foundry build` refuses to overwrite a non-empty destination; remove `bundle/` first.
