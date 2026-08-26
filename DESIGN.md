# Domain Foundry design system

The first-party Foundry surface is an evidence-led product workbench, not a
chat transcript or generic dashboard. Its reference implementation is
`app/src/components/FoundryStudio.tsx`; the generated apps intentionally inherit
their own `FoundrySpec.experience.visual_world`, not this shell.

## Foundry Studio

The visual direction is a documentary edit bench: near-black workspace, warm
paper decision surfaces, slate evidence, amber selections, and literal red
failures. Research, Three cuts, Model + experience, and Owned app form a visible
sequence. Film language is always paired with plain product language so the
metaphor never obscures schema or accessibility terms.

The hierarchy is current decision, its evidence/user rationale, competing
product cuts, derived model/experience, then proof. A concept must differ in
primary loop, hierarchy, and affordance—not merely styling. Remix controls keep
base concept, borrowed fragment, reason, and lineage visible.

At narrow widths the stage rail scrolls as a compact control and all work
surfaces collapse to one column. Controls use visible labels, 44-pixel minimum
targets, strong `:focus-visible` outlines, literal errors, and no color-only
state. Motion is limited and removed when the user prefers reduced motion.

## Generated applications

Generated apps share only trusted primitives: landmarks, skip links, keyboard
focus, dialogs, form controls, status announcements, escaping, export, local
persistence, provenance, responsive reflow, and reduced-motion behavior.
Their navigation topology, density, vocabulary, primary view, layout, color,
and signature elements come from the domain experience contract.

Shared runtime does not mean one generic record list. Typed region contracts
select chart, timeline, comparison, canvas, session, shelf, inspector, or
workbench behavior. Typed actions select create, immutable update, correction,
or reveal behavior. Backup/restore, validation, selection, empty states, and
version history remain consistent safety primitives across those worlds.

All visual tokens are concrete six-digit colors validated by the spec. Browser
automation blocks serious/critical accessibility violations and page overflow
at 320 CSS pixels. Manual screen-reader flows and professional visual review
remain release evidence rather than automated claims.

## Writing

Use direct domain language. Say what evidence supports, what the user chose,
what will be built, and what failed. Never call a generic scaffold researched,
imply that a source validated the generated product, or turn uncertainty into a
confident feature claim.
