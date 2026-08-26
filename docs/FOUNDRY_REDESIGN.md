# Foundry redesign and gap-remediation record

Status: implemented candidate; automated gates pass incrementally, human release
gates remain explicit.

## The gap

Conversation plus a coding harness is easy to reproduce and provides little
durable advantage. The previous creation path did not reliably research an
interest, distinguish product hypotheses, derive storage from real workloads,
preserve design intent, or prove that preview and export were the same product.
It could therefore produce a pleasant generic shell without earning the claim
of a personalized, expert-designed application.

The redesigned product is an inspectable compiler chain:

```text
user practice + artifacts + independent tasks
                ↓
reviewed corpus + bounded live discovery
                ↓
three structurally different product cuts → explicit remix
                ↓
workloads → identity/lifecycle/relationships/time → schema
                ↓
task topology + domain visual world + critical states
                ↓
one FoundrySpec → exact preview + owned app + DDL + evidence + receipt
                ↓
independent schema, task, accessibility, security, license and build gates
```

The repository moat is the maintained knowledge fabric, typed intermediate
representation, deterministic compiler, distinct vertical goldens, and
evaluation corpus. Staff-title role play is deliberately not a mechanism.

The comparative research behind the remix boundary is maintained in the
[AI remix landscape](remix-landscape.md). It distinguishes playable-to-editable
remix, project copy, template fork, design branch, and prompt adaptation across
paid and open-source products instead of treating every “remix” claim as the
same operation.

## Deliverable 1: end-to-end product flow

The interactive [Foundry flow prototype](prototypes/foundry-flow.html) contains
the exact compiled versions of three reviewed verticals:

| Interest | Product center | Schema consequence | Experience consequence |
|---|---|---|---|
| Sourdough practice | Compare fermentation decisions and outcomes | Starter/feed/bake observations remain time-aware events linked to canonical recipes and outcomes | Timeline/lab-bench composition optimized for comparison and measurement |
| Trading-card collecting | Understand owned instances, set completion, and provenance | Canonical cards are separated from owned copies, acquisition events, binder positions, and valuations | Spatial binder canvas with collection gaps as the primary affordance |
| Japanese study | Decide what to review next and adapt from performance | Study items are separated from attempts and scheduling state with explicit transitions | Focused session topology centered on one recall decision at a time |

Each golden has three competing concepts, at least six entities, named
workloads and derived indexes, realistic records, a distinct navigation
topology and visual world, and independent release cases. The first-party
`/foundry` route lets a user author the brief and two acceptance tasks, compare
three cuts, document a selection/remix, inspect the model and proof contract,
and open the exact owned HTML artifact.

## Deliverable 2: how professional guidance enters the product

The interactive [knowledge-fabric prototype](prototypes/knowledge-fabric.html)
shows the editorial system. Reusable guidance is stored in
`knowledge/source-registry.yaml` and three discipline files under
`knowledge/principles/`. Every source records authority, license, allowed use,
status, topics, retrieval date, freshness, and review. Every principle records
the rule, required evidence, failure signals, and source IDs.

The current slate covers:

- Data engineering: workload-first modeling; stable identity; lifecycle and
  temporal separation; stored constraints and referential actions; provenance;
  explainable indexes; privacy; evolvability and migration evidence.
- Product/UX: start from a real user need; three structural concepts; task-fit
  information architecture; domain-specific visual systems; complete states;
  accessibility; responsive/reduced-motion behavior; visible evidence and
  user-controlled remix lineage.
- Software engineering: one typed contract; deterministic builds; boundary
  validation and least privilege; declarative extensions; independent tests;
  observability and receipts; dependency/license evidence; threat modeling;
  reproducible release gates and honest claims.

The corpus draws on primary standards and maintained implementations, including
[PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html),
[W3C PROV](https://www.w3.org/TR/prov-o/),
[GOV.UK design principles](https://www.gov.uk/guidance/government-design-principles),
[WCAG 2.2](https://www.w3.org/TR/WCAG22/),
[ARIA APG](https://www.w3.org/WAI/ARIA/apg/),
[Figma's open design system](https://github.com/figma/sds),
[Storybook](https://github.com/storybookjs/storybook),
[OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/),
[SLSA](https://slsa.dev/spec/v1.2/), and
[SPDX](https://spdx.github.io/spdx-spec/v3.0.1/). Domain exemplars are recorded
with the same license and allowed-use discipline.

Live discovery can fill a vertical gap, but its snippets are untrusted and its
sources remain build-local/reference-only until human review. If neither the
reviewed corpus nor a configured adapter supplies credible vertical evidence,
the product stops instead of presenting a generic scaffold as researched.

## As-built safeguards

- Six narrow typed model stages; closed identifiers at every handoff.
- At least two user-authored evaluation tasks; the model cannot invent its only
  judge.
- SQL identifier/check-expression restrictions and executable SQLite tests.
- HTML escaping, offline-only CSP, sandboxed preview, and a versioned
  contract-interpreting runtime. Region kinds compile to distinct chart,
  timeline, comparison, canvas, session, shelf, inspector, and workbench
  behaviors; action kinds are closed before build.
- Immutable local correction history plus spec-bound JSON backup and validated
  restore. Browser gates create a domain record in each golden, verify
  provenance and derivations, round-trip a correction with its supersession
  chain, reject a foreign backup, and prove imported markup remains inert.
- Atomic bundle construction, deterministic outputs, and hashes for every
  owned artifact.
- Source freshness/allowed-use audit, an exact locked-runtime license policy,
  complete bundled-JavaScript notices, a resolved-license SPDX SBOM,
  Python/npm vulnerability audits, read-only CI permissions, build provenance
  attestation, axe checks, and 320-pixel reflow checks.
- A separately dated provider-compatibility registry sourced from official model
  catalogs; the release audit expires it after 30 days and live probes remain a
  separate exact-artifact gate.
- Seven-day public-name evidence that distinguishes a PyPI 404 from a reservation,
  records the occupied GitHub organization and material exact-mark trademark
  collision, and requires rename/rights/qualified-clearance disposition plus
  explicit maintainer coordinate and publication approval.

## Release definition

The open-source code candidate may be tagged only when the aggregate audit,
clean package build, clean-checkout installation, and all automated browser
tests pass. Product claims additionally require an independent editorial
review of the knowledge corpus, live probes for documented providers, a manual
screen-reader pass, an external security review, and observed use by people
outside the authoring team. These human gates are kept separate so automation
cannot manufacture release confidence.

`scripts/candidate_gate.sh` binds the machine evidence to the source tree and
artifacts. `scripts/public_release_audit.py` then requires seven human receipts,
including name and publication authority, before a tag can be described as a
public release. The complete reviewer protocol is in
[`docs/release-review-guide.md`](release-review-guide.md).

Future work must deepen the knowledge corpus and add held-out verticals without
adding domain-name branches to core. A vertical that only changes nouns, colors,
or fixture values fails the generalization gate.
