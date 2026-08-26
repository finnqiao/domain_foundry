# Contributing to the knowledge fabric

Knowledge contributions are evidence changes, not link-list additions. A
reviewer should be able to tell what a source may support, how it may legally be
used, when it was checked, and which principle or golden decision depends on it.

## Add or update a source

1. Prefer primary standards, official documentation, peer-reviewed research,
   or maintained open-source implementations. Product pages are useful as
   workflow references, not proof that a pattern is universally correct.
2. Add the source to `source-registry.yaml` with a stable identifier, direct
   URL, publisher, tier, license, allowed uses, status, retrieval date,
   freshness window, topics, and reviewer.
3. Use `reference_only` when licensing or authority permits facts and patterns
   to be paraphrased but not copied. Do not copy code, prose, brand assets, or
   screenshots unless the recorded allowed uses and license permit it.
4. Make claims atomic and bounded. “This source defines foreign-key delete
   behavior” is reviewable; “this source proves our schema is correct” is not.
5. Run `python scripts/knowledge_audit.py`.

## Add or update a principle

Each principle needs a stable discipline-prefixed ID, an operational rule,
required evidence, failure signals, and source IDs. It should change an
observable design or release decision. Generic advice that cannot fail a build
does not belong in the corpus.

Changes to release-blocking rules require review from someone other than the
author. A source that is stale, deprecated, license-unknown, or merely a
discovery result cannot be the sole basis for a release-blocking principle.

## Add a vertical exemplar

A reusable golden vertical needs cited domain evidence, realistic synthetic
records for every entity, named workloads, enforced relationships and
constraints, three structurally different product concepts, a domain-specific
experience, and independent task/schema/accessibility/security cases. It must
remain mechanically distinct from existing goldens; color and noun replacement
do not count.

Discovered sources may remain build-local snapshots. Promotion into the shared
registry is a human editorial act and must record the reviewer.
