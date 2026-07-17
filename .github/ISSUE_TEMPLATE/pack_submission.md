---
name: Pack submission
about: Propose a community Domain Pack for the gallery
title: "[pack] "
labels: [pack-submission]
assignees: []
---

<!--
Packs are DATA, not code (six YAML files). A pack must pass `pack validate` and
route its own examples in dry-run before it can be listed. Use synthetic
examples only.
-->

## Pack summary

- **Name** (snake_case, `^[a-z][a-z0-9_]{1,62}$`):
- **Title / one-line description:**
- **Core objects** (event vs entity):
- **License** (MIT recommended for the gallery):

## Why this domain

What passion does it serve, and who would use it?

## Validation evidence

- [ ] `domain-foundry pack validate <name>` passes.
- [ ] ≥8 example utterances, each routes to its intended object in dry-run.
- [ ] ≥2 negative examples that must NOT route.
- [ ] Numeric fields declare a `unit`; enums use `allow_other` where sensible.
- [ ] Events and entities have disjoint routing vocabularies.
- [ ] Synthetic data only — no real names, places, or personal content.

```
paste `pack validate` output here
```

## Manifest (paste `pack.yaml`)

```yaml
# pack.yaml
```

## How to submit

Open a PR adding the pack under `packs/<name>/` (or link a repo), or paste the
six files here for review. See the
[pack authoring guide](../../docs/PACK_AUTHORING.md) and the
[gallery](../../docs/gallery.md#community-candidate-list) for good candidates.
