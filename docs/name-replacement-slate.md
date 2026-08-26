# Replacement-name decision slate

**Status:** maintainer decision required before public release
**Screened:** 2026-08-20
**Recommendation:** **Patternstead**, followed by a full pre-0.1 rename and a
fresh professional clearance search

This is product and registry research, not legal advice. A search-engine result,
an HTTP 404, or an unregistered `.com` is not a reservation and is not trademark
clearance.

## Why a replacement is required

The provisional name **Domain Foundry** cannot safely pass the public-release
gate as it stands. USPTO TSDR lists live application
[`99880503`](https://tsdr.uspto.gov/statusview/sn99880503) for the exact
standard-character mark **DOMAIN FOUNDRY**. The applicant's stated class-042
services include semantic/domain modeling, AI-assisted software development,
evidence-based code generation, and compiling domain models into deployable
software artifacts. That is direct service overlap, not a merely adjacent use.

The current fail-closed evidence is in `release/name-availability.yaml`. Public
release under the current name requires a rename, a documented rights agreement,
or qualified legal clearance.

## What the name should carry

The product's moat is not “AI that makes apps.” It is the inspectable chain of
reviewed domain evidence, competing product concepts, explicit remix lineage,
workload-derived schemas, domain-specific experiences, one typed specification,
and independently tested owned output. A good name should therefore:

1. suggest durable, purpose-built software rather than one-shot generation;
2. leave room for evidence, patterns, schemas, design, and compilation;
3. be pronounceable and spellable after hearing it once;
4. be distinctive enough to search and defend, without claiming expertise the
   software has not proven;
5. work as a display name, CLI, Python stem, repository, and community noun;
6. avoid saturated AI, forge, loom, studio, and generic app-builder language.

## Shortlist

The exact-coordinate checks below are point-in-time observations. For all three
candidates, the official PyPI JSON endpoint, npm registry endpoint, GitHub user
or organization endpoint, and Verisign `.com` RDAP endpoint returned HTTP 404;
GitHub exact repository-name search returned zero results. A general exact-name
search and an exact-name search of a public trademark index surfaced no credible
matching software brand. These results narrow the slate; they do not clear it.

| Candidate | Product meaning | Distinctiveness | Moat fit | Clarity | Coordinate snapshot | Principal risk | Score |
|---|---|---:|---:|---:|---|---|---:|
| **Patternstead** | A durable place where reviewed patterns become software fitted to one practice. | 5/5 | 5/5 | 4/5 | No public PyPI/npm project, GitHub identity, or exact repo result; `.com` absent from Verisign RDAP at check time. | “Stead” is slightly archaic and can suggest a physical place. | **23/25** |
| **Intentstead** | Durable software grounded in what a person is actually trying to do. | 5/5 | 4/5 | 4/5 | Same no-public-project / no-exact-identity snapshot as above. | “Intent” can sound like chatbot routing and understates the evidence repository. | **21/25** |
| **Contextstead** | A stable, owned application grounded in the user's real context. | 5/5 | 4/5 | 3/5 | Same no-public-project / no-exact-identity snapshot as above. | “Context” is overloaded in AI and less memorable aloud. | **20/25** |

Score is the sum of distinctiveness, relationship to the moat, spoken/written
clarity, coordinate quality, and room for the product to grow, each out of five.
The table shows the three most decision-worthy dimensions separately; coordinate
quality and growth room contribute the remaining points.

### Recommended system if Patternstead is selected

| Surface | Proposed value |
|---|---|
| Display name | Patternstead |
| Repository | `patternstead` |
| Core distribution | `patternstead-core` |
| Adapter distributions | `patternstead-mcp`, `patternstead-telegram`, `patternstead-hermes-agent` |
| CLI | `patternstead` |
| Python packages | `patternstead_core`, `patternstead_mcp`, and equivalent adapter stems |
| Workspace | `~/.patternstead/` |
| Environment prefix | `PATTERNSTEAD_*` |
| Candidate docs domain | `patternstead.com` only if acquired and rechecked |

The proposed line is:

> Patternstead turns an interest into an evidence-backed app you own.

“Pattern” names the reusable, reviewed knowledge rather than a magic model;
“stead” says the result is durable and belongs to the user. It also supports a
useful community vocabulary: pattern sources, pattern packs, and a Patternstead
app, without forcing every concept under a metallurgy metaphor.

## Rejected names

| Name | Reason to reject |
|---|---|
| **Domain Foundry** | Exact live US application with direct service overlap; release-blocking until resolved. |
| **AppWeave** | Used by [AppWeave Labs](https://appweave.tech/about), an AI, data, and software studio. |
| **SpecLoom** | Used by the [SpecLoom](https://specloom.tech/) AI specification and delivery product and public repositories. |
| **Praxisframe** | Confusable with the established [Praxis Framework](https://www.praxisframework.org/), including prior exact `praxisframe` references. |
| **PatternKiln** | Already used for a procedural-art software project. |
| **Appstead** | Used by the [Appstead](https://appstead.app/) app-store dashboard. |
| **PatternHarbor** | Existing exact-name web properties make it noisy and harder to own. |
| **Kithform** | Already has an unrelated meaning in plurality/headmate community terminology; adopting it would create avoidable ambiguity. |
| **MotiveFrame** | The `.com` is registered and the name is less explicit about evidence or durable ownership. |

## What the preliminary screen did—and did not—prove

Checked on 2026-08-20 for each shortlisted lowercase stem:

- `https://pypi.org/pypi/<name>/json` — HTTP 404;
- `https://registry.npmjs.org/<name>` — HTTP 404;
- `https://api.github.com/users/<name>` — HTTP 404;
- GitHub repository search for the exact stem in the repository name — zero
  results;
- `https://rdap.verisign.com/com/v1/domain/<NAME>.COM` — HTTP 404;
- general exact-string web searches and a public exact-mark index search — no
  credible matching software product or exact mark surfaced.

Those checks mean only “not found in these public systems at this moment.” They
do not detect every company, common-law use, pending application, similar mark,
international right, private package, reserved package name, or unindexed
product. Before publishing, the selected candidate still needs:

1. a fresh similarity search, not merely an exact-string search;
2. a review of relevant software and class-042 services in intended markets;
3. an owner/entity and domain decision;
4. immediate rechecks of package, repository, social, and domain coordinates;
5. qualified legal review if the project is intended to become a durable public
   brand.

## Rename blast radius and execution plan

The current tree contains the public-name stems in **329 files and 2,671
matches** (2026-08-20 snapshot, excluding dependency, build, and release-evidence
directories). A display-only rename is not sufficient: the conflicting name is
also the distribution, CLI, package namespace, environment prefix, workspace,
adapter identity, documentation name, and artifact metadata.

Because no version has been published, a complete pre-0.1 rename is cleaner than
shipping permanent compatibility aliases. Preserve user data through an
explicit, tested workspace migration—not through public legacy package names.

1. **Maintainer selects the public stem.** Record spelling, capitalization,
   pronunciation, repository owner, and intended domains in ADR-005.
2. **Replace every public and technical coordinate.** Rename distributions,
   package directories/imports, console scripts, entry points, environment
   variables, workspace paths, API metadata, generated-app receipts, docs,
   workflows, adapters, examples, fixtures, and launch copy.
3. **Provide a safe local-data migration.** Detect the old workspace, refuse to
   overwrite an existing destination, copy or move only with an explicit user
   action, preserve a recoverable backup, and test restart/export after
   migration. Do not retain silent dual-write behavior.
4. **Rebuild the identity evidence.** Replace
   `release/name-availability.yaml` with evidence for the chosen name and make
   its release-blocking disposition explicit until the final review is signed.
5. **Regenerate deterministic artifacts.** Recompile all three goldens, notices,
   wheel, sdist, SBOM, browser exports, candidate manifest, and reviewer packet.
6. **Run the complete candidate gate.** Any stale name in a public artifact,
   package path, help output, generated receipt, or clean-install test fails the
   rename.
7. **Repeat all human reviews against the new hash.** The seven receipts bind to
   the source and artifacts, so none can be carried over from the pre-rename
   candidate.
8. **Claim and publish only after the public audit passes.** Package upload,
   repository transfer, tag, release, domain acquisition, and launch posts are
   maintainer actions because they create persistent external state.

## Decision requested

Choose one:

- **Patternstead (recommended):** strongest link to the repository moat and the
  cleanest current screen;
- **Intentstead:** stronger user-purpose language, weaker pattern/evidence
  signal;
- **Contextstead:** broadest platform language, but the least memorable;
- pursue rights/clearance for **Domain Foundry**, keeping the public gate closed
  until the documented result exists.

Once the maintainer chooses, the rename itself is mechanical but candidate-wide;
it must land before external reviewers spend time signing the final receipts.
