# Skill: domain_foundry (capture-first)

You have a **domain_foundry** harness attached — a local-first, capture-first
store for the user's tracked life domains (baking, plants, food, travel, and any
domain they've created). It is authoritative; you are a courier for the user's
words, not the source of truth.

## When to act

- The user **reports something that happened** in a tracked domain (a bake, a
  plant watered, a meal out, a trip plan, a cooking idea) → call
  `domain_foundry_capture` with their message **verbatim**. Do not paraphrase,
  pre-structure, or drop details. The harness parses, routes, and stores it.
- The user **amends or contradicts** a prior capture ("actually it was 80% not
  75%", "that was the rye starter not wheat") → call `domain_foundry_correct`
  with their correction sentence. One message, one correction — never re-capture.
- The user **asks "what did I…" / "when was my last…"** → call
  `domain_foundry_ask` (read-only, grounded in their records). Use
  `domain_foundry_query` when you need the raw rows.
- There are **pending approvals** → surface them with
  `domain_foundry_review_list`; only call `domain_foundry_review_resolve` after the
  user explicitly approves or rejects.
- The user wants to **track a brand-new kind of thing** → call
  `domain_foundry_new_domain` and relay the idea options (pitches, not a
  taxonomy). Do not pick an idea or a look for them. Continue with
  `domain_foundry_wizard_reply` through **looks** until they accept one
  (`build it` / `the scatter one`). If they have photos or a notebook scan,
  **OCR them yourself** and send the text; Foundry files text and can ingest a
  notes folder path. Use `domain_foundry_atlas_search` to browse without
  installing.

## Rules

1. **Never invent structured fields.** Capture raw text; the harness fills
   fields and reports its routing/confidence back in the receipt.
2. **Verbatim capture.** The value is in the user's exact phrasing.
3. **Corrections are one-shot.** Use `domain_foundry_correct`, not a new capture.
4. **Reads are free, writes go through capture/correct.** There is no privileged
   write path — mirror that discipline.
5. **Respect review.** Auto-applied items need no action; queued items wait for a
   human decision.

## Example

> User: "i collect pokemon cards"

→ `domain_foundry_new_domain` → relay the idea options (Card dex is one). Do not pick.

> User: "a dex of the cards i own with photos"

→ `domain_foundry_wizard_reply` → looks. Wait until they accept (`build it`).

> User: "pulled a holographic Charizard from a 151 booster, NM"

→ `domain_foundry_capture(text="pulled a holographic Charizard from a 151 booster, NM")`
   → receipt: routed to `pokemon.card`, applied.

> User: "that Charizard was LP not NM"

→ `domain_foundry_correct(text="that Charizard was LP not NM")`
   → receipt: revision on the same card, `notes: LP`.
