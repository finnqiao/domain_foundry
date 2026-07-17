---
name: Routing miss
about: A capture routed to the wrong object/operation/fields (or didn't route)
title: "[routing] "
labels: [routing]
assignees: []
---

<!--
Use SYNTHETIC data only. If the real capture was personal, invent an equivalent
sentence that reproduces the same misroute. A good routing-miss report is
basically a failing eval case — attach it as one and we can turn it into a
permanent regression test.
-->

## The capture (synthetic)

```
<the exact text you captured>
```

## Active packs

Which packs were active (e.g. `food`, `travel`, `plants`)?

## What it did

- Routed to: `pack.object` / operation / fields (or "unfiled" / "no match")
- Confidence / disposition (auto_apply / review / unfiled), if known:

## What it should have done

- Expected: `pack.object` / operation / fields:

## Proposed eval case (optional but very helpful)

```json
{"input": "<synthetic capture>", "expect": {"object": "plants.care_event", "operation": "create", "fields": {"action": "water"}}}
```

## Checklist

- [ ] Synthetic data only.
- [ ] I listed the active packs.
- [ ] (Optional) I attached an eval-case line the maintainers can drop into a corpus.
