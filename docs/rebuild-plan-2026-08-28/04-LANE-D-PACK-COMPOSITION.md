# Lane D: Pack Composition (M2)

**Goal:** packs stop being islands. A pack can extend another pack and import pieces from it, and cross-pack links compile to real foreign keys, so "diving plus photography" becomes buildable as one app with a real join. This is WS5, graded P0 (quiz Q6=A).

**Size:** M (about 1 week). **Start:** after Phase 0, fully parallel with B, C, E, F.

## Teardown evidence this lane answers

| Finding | Location (verified 2026-08-27; re-locate by content on drift) |
|---|---|
| No composition primitive exists: no extends, imports, or merge anywhere in the pack model | `packs/models.py:26-40, 181-191` |
| The single cross-pack link in the corpus is explicitly skipped by the validator | `packs/loader.py:513-517` ("Cross-pack links are declarative references… continue") |
| The DDL compiler iterates only `obj.fields`, never `obj.links`: no column, no FK, ever | `packs/schema_compiler.py:57-81` |
| Cross-domain behavior today is an LLM prompt hint, not a schema fact | `packs/travel/routing.yaml:87-88`, `routing/router.py:652` |
| The pack ingress seam (entry points, conformance) is real and must not break | `packs/loader.py:891, 920-937`, `scripts/pack_conformance.py` |

## Files owned

`core/domain_foundry_core/packs/models.py` · `core/domain_foundry_core/packs/loader.py` · `core/domain_foundry_core/packs/schema_compiler.py` · `scripts/pack_conformance.py` · `packs/_template/` · `core/domain_foundry_core/cli_stack.py` (new: the `stack` verb) · related tests · `docs/PACK_AUTHORING.md` composition section

Note: `packs/models.py` is this lane's own file (distinct from `foundry/models.py`, which is frozen after Phase 0).

## Design constraints

- Packs remain declarative data (ADR-004). Composition is declared in YAML, resolved by the loader, and rejected loudly on conflicts. No executable extension mechanism.
- Existing packs and third-party entry-point packs must load unchanged. Every new key is optional.
- The compatibility contract (`capabilities.yaml`, core version ranges) keeps rejecting unknown constructs before a pack is usable.

## Phases

### D1: the composition model

- [ ] `packs/models.py`: add optional `extends: <pack>` (single inheritance of schema, routing, projections, with child-wins merge) and `imports: [{from: <pack>, object: <name>}]` (bring a named object in by reference, no copy).
- [ ] `loader.py`: resolve `extends` and `imports` at load time against installed packs; unknown pack, unknown object, or a name collision is a load error with a plain message naming both sides. Cycles are load errors.
- [ ] Merge rules documented in `docs/PACK_AUTHORING.md`: child overrides parent per key; routing rules concatenate child-first; projections concatenate; policy is child's own.
- [ ] Tests: extends merge, import resolution, collision, cycle, unknown target; existing packs load byte-identically when they use neither key.
- [ ] Gate: suite green with counts; `pack_conformance.py` green on all bundled packs.

### D2: cross-pack links become foreign keys

- [ ] `loader.py:513-517`: replace the skip with real validation. A `to: <pack>.<object>` link resolves against installed packs (including imports); a dangling target is a load error when the target pack is installed and a recorded soft dependency when it is not.
- [ ] `schema_compiler.py`: compile links to columns plus `FOREIGN KEY` constraints across the namespaced tables (`{pack}__{object}`), with `ON DELETE SET NULL` as the default referential action. Migration path for existing databases: additive column plus constraint on next schema apply, never destructive.
- [ ] The existing `source_link` LLM mechanism keeps working; where a schema FK exists for the same relation, apply writes both, and the FK is the truth the views read.
- [ ] Tests: travel→food compiles to a real FK; insert with a dangling reference fails at the database; uninstalling a target pack is blocked with a plain message while references exist.
- [ ] Gate: suite green with counts; the Gate-1 three-ingress journey test untouched and green.

### D3: the `stack` verb

- [ ] `cli_stack.py`: `stack <pack-a> <pack-b> [name]` scaffolds a composed pack (extends a, imports the chosen objects of b, one starter view that joins them) and prints, in plain words, what got connected and one example capture that exercises the join.
- [ ] Interactive object choice when b has more than three objects; `--objects` flag for scripts.
- [ ] Tests: stacking two bundled packs produces a loadable pack whose join compiles; the printed example capture routes and applies.
- [ ] Gate: suite green with counts.

### D4: conformance and template

- [ ] `pack_conformance.py` covers extends, imports, and cross-pack links (valid and invalid fixtures).
- [ ] `packs/_template/` gains a commented example of each new key.
- [ ] `docs/PACK_AUTHORING.md` composition section written in the copy rules' voice.
- [ ] Gate: conformance green on bundled packs plus new fixtures; suite green with counts.

## Definition of done

`stack dive photo` (or the bundled equivalent: `stack travel food`) produces one app where a record in one domain holds a real, database-enforced reference to a record in the other, and June's scene 7 first command works as written.

## Out of scope

The FoundrySpec side of composition (specs already model relationships; the P1 merge unifies the two). A piece library or marketplace (Q6 option B territory, not chosen). Backend targets (P1 WS8).

## Resume notes

(append here)
