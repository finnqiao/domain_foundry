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

### 2026-08-28, D1 through D4 landed

All four phases are done and green. Nothing is committed: the integrator commits.

**Test counts.** Lane gate (my two new files plus every existing pack suite and
the Gate-1 journey): **103/103 passed**. Broader regression sweep across apply,
importer, projections, hardening, travel HTTP, api, refile, export, capture,
app shell, search, curated contract, routing eval, and `tests/security`:
**64/64 passed**. Wizard, mesh foundation, eval regression, and
`tests/conformance`: **65/65 passed**. `ruff check` and `ruff format --check`
clean on every file I touched. I did not run the full suite (six agents share
this tree).

**Files changed.**

- `core/domain_foundry_core/packs/models.py`: `PackImport`, `ImportedObject`,
  `link_column()`, `LinkSpec.target_pack/target_object`, manifest `extends` and
  `imports`, `DomainPack.inherits/imports/soft_dependencies/extends/link_target`.
- `core/domain_foundry_core/packs/loader.py`: `default_pack_resolver`,
  `resolver_for_packs`, `_compose`, `_merge_parent`, `_resolve_link_targets`,
  `_add_link_columns`; `load_pack(..., resolver=)`; referential actions allowed
  through the migration SQL scan.
- `core/domain_foundry_core/packs/schema_compiler.py`: `link_columns`,
  `compile_ddl(..., available_packs=)`, `installed_pack_names`,
  `_apply_additive_columns`, `uninstall_blockers`.
- `core/domain_foundry_core/cli_stack.py` (new): the `stack` verb.
- `scripts/pack_conformance.py`: `composition` check plus prerequisite install.
- `packs/_template/pack.yaml`, `packs/_template/schema.yaml`: commented examples.
- `docs/PACK_AUTHORING.md`: new "Putting two packs together" section.
- `tests/unit/test_pack_composition.py` (new), `tests/contract/test_cli_stack.py` (new).

**Design choices worth knowing.**

- `extends` and `imports` live in `pack.yaml`. Both optional.
- A link compiles to a `{link}_uid TEXT` column plus
  `FOREIGN KEY ({link}_uid) REFERENCES {pack}__{object}(object_uid) ON DELETE SET NULL`.
  The column is a real field on the object, which is how the apply engine writes
  it without `apply/engine.py` (not mine) changing at all.
- The FK is emitted only when the target pack is installed in the same database.
  Otherwise the column is still there and the link is recorded in
  `pack.soft_dependencies`. Pointing a constraint at a missing table would make
  every insert fail.
- `apply_pack_schema` now runs an additive `ALTER TABLE ADD COLUMN` pass before
  the DDL, so existing databases gain columns and never lose rows.
- Policy merge: the child's policy when the child declares any rows or UI
  actions, otherwise the parent's. The lane doc says "policy is child's own";
  inherit-on-empty is what makes `stack` produce a working pack without copying
  the parent's policy file. Documented in `PACK_AUTHORING.md`.
- Inherited links that named the parent pack are retargeted to the child, so
  `travel_food__timeline_item.trip_uid` references `travel_food__trip`, not
  `travel__trip`.
- An inherited `agent.yaml` is renamed to the child pack, because validation
  requires `agent.name == pack.name`.

**Evidence the join is real.** `stack travel food` installs `travel_food` and
`sqlite_master` holds:

```sql
CREATE TABLE travel_food__timeline_item (
    ...
    trip_uid TEXT,
    dining_uid TEXT,
    FOREIGN KEY (trip_uid) REFERENCES travel_food__trip(object_uid) ON DELETE SET NULL,
    FOREIGN KEY (dining_uid) REFERENCES food__dining(object_uid) ON DELETE SET NULL
)
```

Inserting a `dining_uid` that does not exist raises `IntegrityError`; deleting
the food dining row clears `dining_uid` and keeps the timeline item.

### Cross-lane requests for the integrator

1. **`core/domain_foundry_core/cli.py`** (integrator-only): add `"cli_stack"` to
   `LANE_CLI_MODULES`. That is the whole registration. Until then `stack` is
   importable and tested but not on the CLI.
2. **`core/domain_foundry_core/packs/registry.py`** (not owned by any lane):
   `uninstall()` should refuse while other packs' records still point at the
   pack being removed. The check is written and tested as
   `schema_compiler.uninstall_blockers(pack_name, self.list(), self.ws.domains_db)`;
   it returns a list of plain messages and an empty list means go ahead. One
   call plus a raise is all that is needed. Until that lands, D2's
   "uninstalling a target pack is blocked" is proved at the function level only,
   not through `pack uninstall`.
3. **`docs/PACK_AUTHORING.md`** has six pre-existing em dashes on lines outside
   my section (35, 47, 59, 60, 70, 89). Lane A owns doc copy, so I left them.

### Known consequence to watch

Every pack with links now gains `{link}_uid` fields, so `field_contract` and
`schema_registry` rows are wider than before. This is additive and every pack
suite is green, but a lane asserting an exact field set on a linked object will
see the new column.
