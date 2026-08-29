# P1 Shelf: right after v0.1

These four workstreams are graded P1. They are scoped here at milestone level so the v0.1 lanes can leave the right seams, and so a fresh agent can pick one up the week after release. None of them may start inside the v0.1 lanes.

## WS6: the merge (one pipeline, one runtime)

**Design reference:** [`../UNIVERSAL_CREATE_RELEASE_PLAN.md`](../UNIVERSAL_CREATE_RELEASE_PLAN.md) is the authoritative design for this work and already carries its own defect table and slice plan. Execute it after v0.1, updated for what the lanes changed.

- The wizard becomes a plain front door to the foundry pipeline; the atlas suggests, it never decides.
- Packs compile from FoundrySpecs; `wizard/bridge.py` and its three-object, sixteen-field caps are deleted.
- The lexical starter shortcut (`blueprint.py:308`) becomes "start from this seed spec", visibly labeled, never an auto-install.
- Exit condition: one creation path; the wizard label from Lane A's A3 ("a quick-capture starter") is removed because it is no longer true.

**Seams the v0.1 lanes must leave:** Lane B's compiler consumes a full spec (it already does); Lane C's review loop takes a proposal object, not a wizard turn; Lane E's seed artifacts attach to the brief, which both paths share.

## WS4: the pattern shelf

Real-app interaction archetypes as citable structures crossed with any passion: a training loop, spaced recall, a collection dex, a bench notebook.

- Each pattern carries: a loop contract, an entity skeleton, a signature view, and an evidence citation for why the loop works (the remix-landscape research in [`../remix-landscape.md`](../remix-landscape.md) is the starting corpus).
- Patterns are data, reviewed into `knowledge/` with the same editorial discipline as sources.
- Pitched in the friend voice and reviewed through Lane C's HTML review loop.
- Exit condition: `pattern list` and applying one pattern to an out-of-corpus passion produces a build whose structure matches the pattern's contract.

**Seams left by v0.1:** Lane F's `TraitEdge` model generalizes to pattern contracts; Lane C's review page renders pattern cards with no new machinery.

## WS8: the backend seam

- `FoundryCompiler` becomes an interface with a registry; the single-file offline target is the default implementation.
- Second target: served-SQLite. `schema.sql` finally executes; the app is served locally against the real database, reusing the daemon.
- The user-facing choice is one plain question: "Where should this live? One file you can open anywhere, or a local app with a real database."
- `standalone_react` either becomes a third target here or is removed from the enum for good; Lane A's allowlist entry expires either way.
- Exit condition: both targets build the same golden from the same spec and pass the same evidence and accessibility gates.

**Seams left by v0.1:** Lane B keeps `compile()` free of target-specific branching outside the template layer it already split in B1.

## WS11: the interest graph contribution loop

The cross-user half of Lane F's local graph. The part that gets better as more people use it.

- `contribute` packages the structure of what a user built: schema shapes, trait edges, vocabularies from public sources, layout choices. It writes a preview page first and sends only on an explicit yes.
- **The sharing line in [`00-OVERVIEW.md`](00-OVERVIEW.md) is binding and worth restating:** public reference links, schema shapes, learned rules, and layout choices can travel after preview and consent; rows from personal uploads, photos, personal vocabulary, and keys never do; anything derived from a personal upload counts as personal.
- Distribution fits the no-hosting rule: contributions land as a versioned, pullable dataset in the open-source repo (a data package under review, like `knowledge/` today), promoted by human editorial review. Every installer pulls the smarter graph; nobody runs a server.
- Exit condition: a contribution round-trips (package, preview, send as a repo submission, review, promote, pull) and a build on a second machine uses the promoted structure; a hostile fixture proves personal rows cannot enter a package.

**Seams left by v0.1:** `SeedProvenance` marks personal versus public at the row level (Lane E); `TraitEdge` is already the exchange format (Lane F); the preview page is Lane C's renderer.

## Not on any shelf

Anything hosted: feeds, accounts, sync services, telemetry. Direct manipulation inside built apps (WS10) and the full lineage system (WS3) stay P2 until the maintainer regrades them.
