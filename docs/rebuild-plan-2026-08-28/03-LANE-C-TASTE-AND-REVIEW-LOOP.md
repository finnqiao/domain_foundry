# Lane C: Taste and the HTML Review Loop (M1c)

**Goal:** taste gets real input channels, all driven from the CLI. `look` generates a local review page the user marks up in the browser (pins, verdicts, token edits); the CLI reads the marks back as structured input; the approved look **binds into the build** instead of being discarded. `tokens` edits the palette, type, and density directly. `vibe` extracts tokens and a pattern from a reference the user supplies. This is WS2, graded P0.

The review loop is a product mechanism, per the maintainer: "any designs for review can be generated htmls for the user to review and interact with and send back."

**Size:** M to L (1.5 to 2.5 weeks). **Start:** after Phase 0, in parallel with Lane B. C codes against the `LookBinding` contract, not against Lane B's files; the two meet at SP2.

## Teardown evidence this lane answers

| Finding | Location (verified 2026-08-27; re-locate by content on drift) |
|---|---|
| Look mockups are generated, critiqued up to 8 rounds, then discarded; only a keyword job id survives | `wizard/looks.py:115` (persisted, never read again), `wizard/engine.py:117` (`_CRITIQUE_RE`, 13 words), `engine.py:930` |
| The only visual affordance in the Studio is nine read-only swatches | `FoundryStudio.tsx:289` |
| `VisualTokens` validates hex but nothing lets a user set them | `models.py:307-318` |
| Look generation exists in two forms: one LLM call or a hardcoded template with 6 bodies and 2 palettes | `looks.py:336`, `looks.py:128-298` |

## Files owned

`core/domain_foundry_core/wizard/looks.py` · `core/domain_foundry_core/review/` (new package: page generator, mark reader) · `core/domain_foundry_core/cli_taste.py` (new: `look`, `tokens`, `vibe` verbs) · `tests/` for all of the above · the SP2 integration test

Shared: `LookBinding` and `BespokeLayer` types live in `models.py` from Phase 0. `cli.py` gets one registration line via the integrator.

## Design constraints

- Local only. The review page is a static HTML file opened from disk; marks are saved to a sibling JSON file the CLI reads (`look --read`). No server, no account.
- The page follows the copy rules: plain language, concrete controls, no em dashes, no cost talk.
- Idea cards on the page use the pitch voice: "Want to log every nudibranch you see? You already have a log of observations and dates. Build a Pokedex-style tracker for it." One line of design and feel after.
- Everything the page can do, the CLI can do without a browser (flags on `look` and `tokens`), so agents and screen-reader users are not second-class.

## Phases

### C1: the review page generator

- [ ] New `review/` package: given a proposal (three concepts plus current tokens), emit `review.html` containing: each concept rendered as a small live preview with the user's sample notes inside (reuse the compiled preview, not a drawing of it), a pitch-voice card per concept, editable token controls (palette swatches, type stack choice, density toggle), pin-a-note on click, a verdict control per concept, and a Save button that writes `review-marks.json` next to the page.
- [ ] Marks schema (documented in the package): chosen concept, token overrides, pins (x, y, text, concept), borrowed fragments (source concept, named piece), free notes.
- [ ] Accessibility: keyboard operable, visible focus, no color-only state, works at 320px.
- [ ] Tests: page generates for the three goldens; marks round-trip through a headless browser writing the JSON; malformed marks are rejected with a plain message.
- [ ] Gate: suite green with counts.

### C2: `look` and `look --read`

- [ ] `cli_taste.py`: `look` compiles previews, writes the page, opens it (or prints the path), and says exactly what to do next in one sentence. `look --read` ingests `review-marks.json`, validates it, and writes a `LookBinding` into the working spec. `look --choose <concept> --tokens <file>` does the same with no browser.
- [ ] The binding persists: `dump` includes it; a re-run of `look` starts from the bound state.
- [ ] Tests: end to end from generated page to bound spec; the no-browser path produces the identical binding.
- [ ] Gate: suite green with counts.

### C3: `tokens`

- [ ] `tokens` prints the current palette, type stack, and density in plain words; `tokens --set accent=#E39A2D --type reading --density bench` edits them with validation from `VisualTokens`; `tokens --page` emits a small review page variant for visual editing.
- [ ] Tests: validation rejects bad hex with a plain message; edits land in the binding.
- [ ] Gate: suite green with counts.

### C4: `vibe`

- [ ] `vibe <image|html|url>`: extract a palette and, where recognizable, a pattern hint from the reference. Image path: palette extraction locally plus one model call for pattern description using the user's key. HTML or URL path: parse stylesheet colors and type. Output is a proposed token set applied to the review page, never auto-committed; the user approves through `look --read` or `tokens`.
- [ ] The reference file never leaves the machine except as the single model call the user's key already implies; say so in the command's one-line description.
- [ ] Tests: fixture image produces a stable palette; fixture HTML produces its declared colors; the approval step is required.
- [ ] Gate: suite green with counts.

### C5: retire the discard path (SP2)

- [ ] `looks.py`: the old generate-and-discard flow is replaced by the review loop; `_CRITIQUE_RE` keyword matching is deleted; the persisted-then-ignored `looks/*.html` output dies.
- [ ] SP2 integration test (owned here): mark up a page for a golden, bind, build through Lane B's compiler, and assert the built app carries the chosen topology, the token overrides, and the borrowed fragment.
- [ ] Gate: SP2 test green; no code path writes a look that nothing reads; suite green with counts.

## Definition of done

June's scene 4 works verbatim: `look`, mark up in the browser, `vibe` a photo, `look --read`, and the approved look compiles into the owned app. The words "the discarded-mockup problem" no longer describe anything in the tree.

## Out of scope

The compiler internals (Lane B). Direct manipulation inside the built app (WS10, P2). The wizard chat flow (P1 merge). Pattern archetypes (WS4, P1).

## Resume notes

(append here)
