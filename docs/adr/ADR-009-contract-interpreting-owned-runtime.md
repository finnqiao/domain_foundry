# ADR-009: The owned runtime interprets the experience contract

- Status: accepted
- Date: 2026-08-20

## Context

ADR-008 made one `FoundrySpec` the source of the preview, schema, evidence, and
owned app. The first compiler preserved that identity but flattened too much of
the experience: most region kinds became record lists, and most actions opened
the same create form. A structurally rich specification could therefore produce
a visually distinct yet behaviorally generic application.

That violated the product contract. Shared safe primitives are desirable; a
single generic shell that ignores the declared task topology is not.

## Decision

The standalone runtime is a versioned, packaged compiler input. It interprets
the typed experience contract without branching on domain names:

- `chart`, `timeline`, `comparison`, `table`, `ledger`, `canvas`, `session`,
  `shelf`, `catalog`, `media`, `inspector`, `workbench`, and `explanation`
  regions have distinct accessible renderers;
- actions are a closed set of `create`, `update`, `correct`, and `reveal`;
- each view closes region and action targets against its declared entities and
  workloads before compilation;
- relationship fields use known target identities where the model declares an
  inline relationship;
- required, scalar, enum, uniqueness, and supported declarative check
  constraints are enforced before local persistence;
- update and correction append a new immutable record version, mark the prior
  version as superseded, and append an operation receipt;
- export includes all versions, active records, receipts, the exact spec,
  evidence, and derivations;
- restore is bounded, spec/version-bound, schema-validated, confirmation-gated,
  and committed only after the entire backup passes;
- imported and generated text is escaped, the CSP remains network-denying, and
  a browser security test proves hostile imported markup remains inert.

The compiler version is `domain-foundry-core/foundry-spec-1.1`; the browser
store schema is version 2. The runtime JavaScript lives beside the compiler as a
packaged source file so clean-wheel builds and source checkouts execute the same
implementation.

## Consequences

The three goldens now differ in behavior as well as nouns and tokens: measured
series render as charts, event evidence as timelines, collection positions as a
canvas, controlled comparisons as tables, and study prompts as a focused reveal
session. Browser gates exercise all three, create and export real records, prove
correction lineage, restore a backup, reject foreign state, and run axe/reflow
checks.

The runtime remains declarative. It does not execute arbitrary generated code or
pretend an unsupported computation happened. New algorithms or projections must
enter as separately reviewed typed capabilities with their own fixtures,
security boundary, and release checks. A prose consequence on an action is not
authority to execute model-authored code.
