# Slice 4 — Ecosystem preview

**Resolution:** milestones + acceptance criteria. Do not start before Slice 3's
capability model is published — the lifecycle and conformance kit are contracts
over that model.
**Governing decisions:** [`00-OVERVIEW.md`](00-OVERVIEW.md) #10 (declarative
packs + separately-installed permissioned behavior adapters; curated gallery
before any open registry) and the review's Gate 4 (safety) + Slice 4 section.

**Goal:** a third party can build, test, publish, install, inspect, and remove a
pack without maintainer hand-holding or hidden trust.

---

## M4.1 Pack lifecycle

Concentrate the full lifecycle behind `PackRegistry` (review deepening candidate
2 — today proposal/validation/installation/activation/migration/registration are
spread across wizard, registry, CLI, and supervisor):

`source → inspect → permissions preview → install → validate (deep) → activate →
upgrade → rollback → export/uninstall`

- **Deep validation** closes the known `pack validate` gap: replay the pack's
  positive *and* negative examples through routing, and check every cross-file
  relationship (schema ↔ operations ↔ projections ↔ migrations ↔ evals), not
  just structural basics.
- **Permissions preview** before install: what the pack can touch, in
  user-readable capability language (the model decided in #10 — declarative
  packs are data; anything beyond gets a separately installed, explicitly
  permissioned behavior adapter).
- **Upgrade/rollback** reuse the Slice 2 hardening snapshot mechanism.

**Acceptance:** the full lifecycle runs end-to-end from both CLI and shell on a
pack that is *not* bundled; uninstall leaves no orphan tables or projections.

## M4.2 Conformance kit + external authors

- Derive a pack-author conformance suite from `tests/conformance/` (built in
  Slice 1): given a pack directory, run lifecycle + routing acceptance + journey
  checks and emit a pass/fail report an author can act on.
- Curated-gallery listing rules: `pack validate` (deep) green + held-out routing
  acceptance + declared compatibility range. Curation stays manual (no open
  registry — decision #10).
- Recruit **3 external pack authors and 3 external users** (review Gates 5/6
  overlap): time-to-first-pack and time-to-activated-foundry measured, friction
  logged as issues.

**Acceptance:** three externally-authored packs pass conformance and are listed;
three external users reach activation unaided; the founder is no longer the only
person who has completed the loop.

## M4.3 Security review (review Gate 4)

Before any non-preview release:

- External security pass over: localhost HTTP threat model (DNS rebinding, Host
  headers, browser-extension reach), custom blocks / side-loaded JS, generated
  SQL identifiers, prompt injection through captured text and pack content
  (including the Ask pipeline's data-not-instructions guard from Slice 1),
  connector capabilities, and subscription-backed agent authority.
- Default-deny external writes and ambient credentials; capabilities presented
  before install/activation and revocable after.
- Fuzz migrations, paths, SQL identifiers, malformed packs, hostile captures
  (extend the existing `tests/security/` suite).
- Publish stable/deprecation policy and compatibility windows.

**Acceptance / slice exit:**

- [ ] Full pack lifecycle green end-to-end (CLI + shell) on a non-bundled pack.
- [ ] Conformance kit runs standalone on an author's machine and its verdict
      matches CI's.
- [ ] 3 external authors published; 3 external users activated; friction issues
      filed and triaged.
- [ ] External security review completed; findings dispositioned; policy docs
      published.
- [ ] Only after all of the above: the "technical preview" label may come off.
