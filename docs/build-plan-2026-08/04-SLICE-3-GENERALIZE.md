# Slice 3 — Generalize only what two domains prove

**Resolution:** milestones + acceptance criteria. Detailed specs are deliberately
deferred: this slice's whole discipline is that seams are extracted from *proven*
implementations, not designed up front. Re-read
[`00-OVERVIEW.md`](00-OVERVIEW.md) decision #1 (sequence A→B→C) and the review's
"Deepening opportunities" §3/§4 before starting.
**Depends on:** Slice 2 complete (travel is the first deep domain).

**Goal (review Gate 3, second and third golden outcomes):** sourdough and
Japanese become genuinely useful domain experiences; then — and only then —
extract the seams all three domains share.

---

## M3.1 Sourdough golden outcome (observational/scientific workflow)

Prove the recipe → bake → observation → learning lifecycle end to end:

- Units and derived comparisons (hydration %, bake-over-bake deltas) as
  pack-declared derived values, not core code.
- Crumb-photo attachment on a bake (the attachments substrate exists in
  `ledger/attachments.py`; what's missing is pack-declared photo capture and a
  gallery rendering in the shell).
- Correct a hydration figure and show the revision + eval history surviving.
- A bake-comparison view that is actually useful (side-by-side of chosen bakes
  with the derived metrics) — this is the forcing function for whatever
  "derived metrics" capability the pack model grows.

**Acceptance:** a real month of bakes logged, compared, and corrected in the
shell; the pack's derived values declared in YAML, with zero sourdough-specific
core code.

## M3.2 Japanese golden outcome (interactive/proactive workflow)

- Card import with reconciliation report (same preview→commit pattern as
  Roamboard).
- Start/resume a quiz session from the shell without blocking any other domain —
  the session primitives exist (`mesh/quiz.py`, `quiz_start/grade/next/stats` on
  `HarnessAPI`); what's new is the shell surface and honest session lifecycle.
- A due-card nudge with time-zone and missed-run policy via the existing
  `evaluate_schedules` — surfaced as a visible schedule the user can pause or
  revoke, not a background mystery.
- Session/activity history visible in the shell.

**Acceptance:** a week of real study driven from the shell; quiz sessions
interleave with captures in other domains; the nudge fires, is visible, and can
be paused.

## M3.3 Seam extraction — the actual point of this slice

After (not before) M3.1 and M3.2:

1. Write a short comparison memo: what did travel, sourdough, and Japanese each
   force into core? (Candidates the review predicts: interactive sessions,
   derived metrics, domain actions, media.)
2. Extract a shared seam **only where two real implementations already exist**
   (the review's rule). One implementation = keep it domain-local; speculative
   generality is the failure mode this slice guards against.
3. Publish the resulting declarative capability + compatibility model in
   `docs/concepts/` — this becomes the contract Slice 4's external pack authors
   build against.
4. Nouns: finalize the product noun system (workspace → domain → record/event →
   action → view → agent/connector → revision) in a repo-root `CONTEXT.md`, per
   the review's benchmark-lessons section.

**Acceptance / slice exit:**

- [ ] Both golden outcomes demonstrated with real data (evidence: command
      transcripts + short films, same standard as Slice 2).
- [ ] Comparison memo written; each extraction justified by two implementations.
- [ ] A new domain with similar needs (pick one: coffee or climbing, from the
      held-out suite) implements without editing unrelated core modules — this
      is the measurable test of the slice.
- [ ] Capability + compatibility model published in `docs/concepts/`;
      `CONTEXT.md` created.
