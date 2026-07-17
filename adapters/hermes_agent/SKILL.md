# Skill: domain_expert (capture-first)

You have a **domain_expert** harness attached — a local-first, capture-first
store for the user's tracked life domains (baking, plants, food, travel, and any
domain they've created). It is authoritative; you are a courier for the user's
words, not the source of truth.

## When to act

- The user **reports something that happened** in a tracked domain (a bake, a
  plant watered, a meal out, a trip plan, a cooking idea) → call
  `domain_expert_capture` with their message **verbatim**. Do not paraphrase,
  pre-structure, or drop details. The harness parses, routes, and stores it.
- The user **amends or contradicts** a prior capture ("actually it was 80% not
  75%", "that was the rye starter not wheat") → call `domain_expert_correct`
  with their correction sentence. One message, one correction — never re-capture.
- The user **asks "what did I…"** → call `domain_expert_query` (read-only).
- There are **pending approvals** → surface them with
  `domain_expert_review_list`; only call `domain_expert_review_resolve` after the
  user explicitly approves or rejects.
- The user wants to **track a brand-new kind of thing** → call
  `domain_expert_new_domain` with their plain-language goal and relay the
  wizard's questions; feed answers back with `domain_expert_wizard_reply`.

## Rules

1. **Never invent structured fields.** Capture raw text; the harness fills
   fields and reports its routing/confidence back in the receipt.
2. **Verbatim capture.** The value is in the user's exact phrasing.
3. **Corrections are one-shot.** Use `domain_expert_correct`, not a new capture.
4. **Reads are free, writes go through capture/correct.** There is no privileged
   write path — mirror that discipline.
5. **Respect review.** Auto-applied items need no action; queued items wait for a
   human decision.

## Example

> User: "baked a 75% hydration country loaf, bulk 5h, came out great"

→ `domain_expert_capture(text="baked a 75% hydration country loaf, bulk 5h, came out great")`
   → receipt: routed to `sourdough.bake`, applied.

> User: "oops that was 80% hydration not 75"

→ `domain_expert_correct(text="that bake was 80% hydration not 75")`
   → receipt: revision on the same bake, `hydration: 75 → 80`.
