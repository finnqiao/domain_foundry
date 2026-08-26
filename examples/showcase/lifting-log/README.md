# Barbell Logbook — showcase target

**TARGET ARTIFACT** — the spec is hand-authored (Phase 0 bar); the bundle beside it is compiled from that spec by the real deterministic FoundryCompiler (`foundry build`), no live LLM involved. The live pipeline's acceptance test is producing a spec of this caliber unaided.

## The interest

I run a written block — right now 5x5 LP — and the only thing that decides next session's load is what actually went on the bar last time. Between sets I have chalk on both hands and about ten seconds, so the log has to take "squat 5x5 at 100kg" the way I would say it out loud and file it against today's prescribed day. When a lift stalls twice I deload on purpose, and I want that week to read as intended training rather than as a hole in the data.

## Acceptance utterances

The finished pipeline's app MUST file both of these. They are the reason this target exists: the current wizard compiles a pack whose only rule is a generic session with a name, a noted-at, and a value — it cannot represent "squat 5x5" at all.

| Utterance | Files as |
|---|---|
| `squat 5x5 at 100kg, last set was a grind` | A **`set_entry`** against today's `session`, with `exercise_id` → the canonical `back squat`, `scheme: "5x5"` kept verbatim, resolved to `sets: 5` / `reps: 5`, `load_kg: 100`, `is_top_set: true`, and `effort_note: "last set was a grind"` held on the set that earned it — not flattened into a session note. |
| `bench 3x8 at 70kg, RPE 8, deload next week` | A **`set_entry`** for the canonical `bench press` with `scheme: "3x8"`, `sets: 3`, `reps: 8`, `load_kg: 70`, `rpe: 8`. "deload next week" is offered as a **`program`** state change (`running` → `deloading`) rather than buried in free text. |

`load_kg`, `rpe`, and `sets`/`reps` are all constrained at the schema level (`load_kg > 0 AND load_kg < 500`, `rpe >= 1 AND rpe <= 10`, `sets > 0 AND reps > 0`), so RPE 14 is rejected before canonical storage.

## Vocabulary bar

An app compiled from this spec has to hold these words without translation. All of them appear in the compiled bundle:

`squat` · `bench` · `deadlift` · `press` · `5x5` · `3x8` · `RPE` · `deload` · `top set` · `working set` · `PR` · `grind` · `AMRAP` · `kg` / `lb`

Structurally, the ones that carry weight:

- **`5x5` is scheme × load**, not a name and a value. The lifter's shorthand is kept verbatim in `scheme` and resolved into `sets` and `reps` beside it, because `5x5` is how the work is said and *five sets of five* is how it must be queried.
- **RPE is per-set effort**, 1–10, on the hardest set — not a session rating.
- **A deload is a state**, not an absence. `program.status` runs `planned → running → deloading → completed`, with `deloading → running` for resuming, so a deliberately lighter week is recorded training.
- **A PR is per-exercise per-rep-range.** There is no single unqualified "PR" number; the `pr_board` index is `(exercise_id, reps, load_kg)`.
- **e1RM is derived, never stored.** Estimated one-rep max is computed from load and reps with Epley at read time (`derived_metrics` capability, workload `w_e1rm_trend`), so it stays traceable to the sets behind it and changes when a set is corrected.

## Files

| Path | What it is |
|---|---|
| `spec.yaml` | The hand-authored FoundrySpec — the Phase 0 bar. 5 entities, 5 relationships, 6 constraints, 4 indexes, 4 workloads, 3 concepts, 4 views, 7 evaluation cases. |
| `bundle/app.html` | Self-contained local application compiled from the spec — capture, correction history, and validated JSON export/restore. |
| `bundle/schema.sql` | Executable SQLite DDL: identities, checks, foreign keys, and workload-derived indexes. |
| `bundle/foundry-spec.json` | The validated spec as the compiler consumed it. |
| `bundle/evidence.json` | Frozen source, principle, citation, and derivation snapshot (`wger_workout` and the standing slate). |
| `bundle/build-receipt.json` | Artifact hashes and compiler identity. |
| `bundle/README.md` | Compiler-generated ownership notes for the bundle. |

## Rebuild

```sh
domain-foundry foundry validate examples/showcase/lifting-log/spec.yaml
rm -rf examples/showcase/lifting-log/bundle
domain-foundry foundry build examples/showcase/lifting-log/spec.yaml \
  --output examples/showcase/lifting-log/bundle
```

The compiler refuses to overwrite a non-empty destination, so remove the bundle before rebuilding.
