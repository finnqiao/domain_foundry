# AI remix landscape and product thesis

Research date: 2026-08-19. Scope: products where an AI-generated interactive
artifact can be discovered, copied, forked, branched, or adapted—not general AI
coding assistants. This is a primary-source feature comparison, not a ranking or
an endorsement. Product behavior changes quickly; the source registry expires
these references after 90 or 180 days.

## What “remix” currently means

The reviewed market uses the same word for several different operations:

1. **Playable-to-editable:** encounter an app or game as a player, then turn it
   into an editable project.
2. **Copy-to-workspace:** duplicate the latest project/files while leaving the
   source unchanged.
3. **Template fork:** inherit a codebase, configuration, design system, or agent
   instructions as a starting point.
4. **Design branch:** preserve the current work while exploring another visual
   direction.
5. **Prompt adaptation:** ask AI to reproduce or modify an observed interface.

Those are useful mechanics, but none alone establishes why the underlying
product, domain model, or interaction topology fits a particular person's
practice. Domain Foundry uses **structural remix** for that missing layer: the
user can combine a concept's job-to-be-done, another concept's entity/lifecycle
model, and a third concept's task topology, with every retained decision named
in the compiled specification.

## Reviewed products

| Product | Reviewed remix surface | What carries forward | What the reviewed sources establish | Boundary relevant to Domain Foundry |
|---|---|---|---|---|
| [Sekai](https://sekai.ai/) | Player-first create, play, remix, and share loop for interactive mini-apps | A playable mini-app becomes a new creative starting point | Community consumption and creation are one loop | The public page does not document workload-derived schemas, semantic decision lineage, or owned build evidence |
| [Rosebud AI](https://lab.rosebud.ai/blog/beginner-guide) | Browse/play a game, then “Remix this game” into My Projects | An editable copy of the selected game | Play precedes authorship; community work teaches by example | Strong interaction remix, but the reviewed guide does not establish professional data-model derivation or inspectable product evidence |
| [Lovable](https://docs.lovable.dev/features/project-visibility) | Explicit public/workspace remix into an independent project | Latest project, source code, and editable working state | The original remains unchanged; project access and published-site access are separate; public remixing is opt-in | Clear copy and privacy semantics, but remix is an exact project copy rather than a typed combination of domain decisions |
| [Replit](https://docs.replit.com/category/replit-apps) | Community app remix plus templates/imports used with Agent | Code, data/assets, configuration, and—through enterprise templates—build instructions | Remix/fork is a first-class creation path alongside AI generation and Git imports | Strong implementation inheritance; the reviewed flow does not expose evidence-to-schema or concept-to-task derivations |
| [Bolt](https://support.bolt.new/building/using-bolt/sharing) | Viewers can duplicate projects; backups restore into a new fork | Project code and an independently editable state | Project sharing is distinct from publishing, and secrets are not exposed to viewers | Good collaboration and fork safety; no reviewed community discovery or semantic remix contract |
| [Base44](https://docs.base44.com/Getting-Started/Quick-start-guide) | Clone/copy an app and allow a visitor to create their own copy | Generated app and Base44-managed backend; ZIP/GitHub export is available | AI supplies design, database, authentication, hosting, preview, and copy/export paths | Broad managed product generation, but the reviewed guide presents the data model as platform-handled rather than workload-explained |
| [v0](https://v0.dev/docs) | Community examples, iterative chats, and Git-backed app editing | Modern web-app code, project context, and deployable preview | Full-stack generation, design inputs, extension points, and community examples | The reviewed official pages do not define a durable remix-lineage object or a domain-research/schema review stage |
| [Websim](https://websim.com/) | A feed makes generated games/apps immediately playable and commentable | Public interactive artifact and its social context | Discovery and use are the primary surface, with creation adjacent | The public surface does not document export ownership, schema reasoning, or exact fork lineage |
| [Magic Patterns](https://www.magicpatterns.com/) | Generate and iterate multiple UI directions using product context | Screenshots, styles, components, and design-system rules | Visual alternatives and real component paths can ground engineering handoff | Deep on interface exploration; outside the reviewed scope are persistent domain schemas and full owned-app compilation |
| [Onlook](https://github.com/onlook-dev/onlook) | Open-source visual editor with design branches, checkpoints, Git import, and PR export | React code, component mapping, tokens/assets, and branch history | Direct DOM-to-code editing and reversible visual experimentation are inspectable | Excellent implementation/design substrate; it does not claim interest research or workload-first data architecture |
| [Dyad](https://github.com/dyad-sh/dyad) | Local, BYO-key prompt-to-app building rather than a public remix network | Locally controlled generated code and provider choice | An open implementation can make privacy and ownership the default | Useful open-source execution reference; community artifact lineage and evidence-backed product derivation are not its documented center |

“Not documented” means the reviewed primary source did not establish the claim;
it is not proof that a product has no such internal capability.

## Patterns worth adopting

- **Start with something concrete.** Sekai, Rosebud, Websim, and community
  galleries shorten the blank-page phase by letting people play before they
  author. Domain Foundry therefore compiles three playable cuts rather than
  returning three paragraphs.
- **Never mutate the source.** Lovable, Bolt, and template forks preserve the
  original. A Foundry remix must create a new spec with explicit parent IDs and
  retained decisions.
- **Separate access from publication.** Lovable and Bolt make an editable
  project different from a hosted result. Domain Foundry similarly separates
  local preview, owned export, and any future public gallery.
- **Carry guidance with the artifact.** Replit templates and Magic Patterns
  design systems show that reusable rules belong in the build context. Domain
  Foundry carries principle IDs, evidence IDs, workloads, task contracts, and
  release checks in the spec—not in an invisible system prompt.
- **Keep visual change reversible and code-addressable.** Onlook branches and
  DOM-to-code mapping support safe exploration. Domain Foundry keeps concept
  lineage and produces one deterministic artifact from one inspectable spec.
- **Ownership must survive the service.** Git/ZIP export and local-first tools
  set the floor. The preview and exported HTML in Domain Foundry are the same
  byte-identical app, accompanied by DDL, evidence, and hashes.

## The defensible product boundary

The moat is not “AI makes an app,” a gallery, or a remix button. Those are
widely available. It is the maintained chain that competitors' reviewed public
materials do not establish end to end:

```text
credible interest evidence
  → three structurally distinct, playable product hypotheses
  → explicit cross-concept remix lineage
  → workload-derived identity/lifecycle/relationship/time model
  → task-fit and domain-specific experience contract
  → deterministic owned app + DDL + provenance + release receipt
```

This comparison creates four non-negotiable release tests:

1. A “remix” that changes only nouns, fixtures, or color tokens fails.
2. A schema with no named workload and evidence path fails.
3. A preview that is not the exact exported app fails.
4. A professional claim that exists only in a prompt and not in the reviewed
   corpus/spec/receipt fails.

## What not to build yet

A public feed, multiplayer editor, managed hosting, and broad framework support
are proven product patterns, but they are not the wedge. Adding them before
external users can understand and trust the concept/schema/experience chain
would trade the unique part of Domain Foundry for expensive parity work. The
open-source release should first prove that structural remix produces a more
specific and better-explained personal app than a blank chat-to-code session.
