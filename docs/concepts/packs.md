# Domain packs

A **Domain Pack** is the remix surface — the single artifact you author (or the
wizard generates) to teach the harness a new domain. A pack is **data, never
code** in v1 ([ADR-004](../adr/ADR-004-packs-are-data.md)): a small set of YAML
files, no arbitrary Python.

For the quality bar and field-by-field style rules, see the
[Pack authoring guide](../PACK_AUTHORING.md). This page is the conceptual tour.

## The six files

| File | Purpose |
|---|---|
| `pack.yaml` | Manifest: `name`, `version`, `title`, `description`, `interpretation`, `aliases`. |
| `schema.yaml` | Object types → fields (+ optional cross-domain links). |
| `routing.yaml` | L1 regex rules, ≥8 example utterances, ≥2 negatives, LLM hints. |
| `operations.yaml` | Allowed operations per object (`create`/`update`/`correct`/`merge`/`delete`). |
| `policy.yaml` | Apply-policy defaults (auto_apply / review / confirm) + never-drop fallback. |
| `projections.yaml` | App views (blocks) + optional markdown vault layout. |

Optional directories: `prompts/` (interpreter prompt fragments), `evals/`
(golden `fixtures.jsonl` shipped with the pack), and `migrations/` (generated
SQL, one file per schema version).

## What "packs are data" buys you

- **`pack validate` is offline and total.** A pack can be fully checked without
  running an LLM or touching your data — schema well-formedness, routing example
  coverage, negative examples, policy sanity.
- **Safe to share.** Installing a pack cannot execute code, so packs can be
  swapped like Obsidian community plugins. The `ApplyEngine` only ever runs a
  **closed operation vocabulary** against the compiled schema.
- **Migratable forever.** Generated and hand-edited packs share one evolution
  path: a plain-language edit → a diff preview → an `ALTER TABLE` migration → a
  `schema_registry` refresh → an appended routing fixture.

## Objects: events vs entities

A recurring modeling decision (baked into the style guide):

- **Event** — a timestamped occurrence, one row per happening: a `care_event`, a
  `bake`, a `run`. Route feeding/observation language here.
- **Entity / regimen** — a long-lived thing updated in place: a `plant`, a
  `starter`. Route acquisition/naming language here.

Keep their routing vocabularies **disjoint** so each example matches exactly one
object.

## Installation & discovery

A pack is installed by any of:

- a directory drop-in at `~/.domain_foundry/packs/<pack>/`,
- `domain-foundry pack add <path-or-git-url>`,
- `pip install domain-foundry-pack-<name>` (entry-point group
  `domain_foundry.packs`),
- a **private overlay** directory listed in `DOMAIN_FOUNDRY_PACKS_PATH`
  (personal packs can live entirely outside this repo — e.g.
  `~/HermesWorkspace/packs/`; see [Private overlay](../PRIVATE_OVERLAY.md)).

Discovery is a directory scan + entry-point scan at startup. Overlay paths load
**after** workspace and entry-point packs so a same-named private pack shadows
the public one. Lifecycle commands: `pack list`, `pack validate`, `pack add`,
`pack upgrade`.

## Trust tiers

Extensibility comes in three explicitly-labeled tiers:

1. **Packs (data).** YAML/SQL/JSONL. Cannot execute code. The default.
2. **Pip-installed handlers (trusted code).** A pack that outgrows declarative
   operations may ship a Python handler *only* via a separately-installed pip
   package registered through the `domain_foundry.packs` entry point — an
   explicit choice by the user to install code.
3. **Side-loaded custom blocks (trusted code).** React components you build and
   drop in; they run in your browser session. See
   [Custom blocks](../CUSTOM_BLOCKS.md).

The three bundled reference packs (`plants`, `sourdough`, `food`, `travel`) are
all Tier 1 — pure data — and were authored through the public pack format only.
See the [Pack gallery](../gallery.md).
