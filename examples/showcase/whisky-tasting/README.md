# Tasting Bench — whisky tasting notes

**TARGET ARTIFACT** — the spec is hand-authored (Phase 0 bar); the bundle beside it is compiled from that spec by the real deterministic FoundryCompiler (`foundry build`), no live LLM involved. The live pipeline's acceptance test is producing a spec of this caliber unaided.

## The interest

Someone pours a dram, noses it, tastes it, and wants the impression written down before the glass is empty and the memory blurs. Over a year that becomes a real body of evidence: which regions they return to, which cask finishes they only think they like, which bottle was worth the money. What they want back is three answers — what is open tonight, how has this bottle tasted across its pours, and which flavors keep earning a high score.

This is the audit's most quietly insulting failure. Typing "whisky tasting notes" today installs **Dev Notes**, because `notes` is four characters long and sits inside a software-decisions alias. The drinker gets fields for `repo ref` and `alternatives`.

## Acceptance utterances

The finished pipeline's app must file both of these without a second pass:

- **"peated dram, iodine and orchard fruit, 12 year, neat"** files one `dram`: `serving` neat, `nose` holding the drinker's own words verbatim, `age_years` 12 read off the age statement, and two `flavor_note` rows (`iodine`, `orchard fruit`) tagged on the `nose` axis. It attaches to the open peated bottle rather than inventing a new one.
- **"opened the Ardbeg 10 tonight, about two-thirds left"** updates one `bottle`: `status` sealed → open, `fill_level_pct` roughly 66. This is a lifecycle transition on an owned object, not a new tasting event, and a spec that models only "notes" cannot express it.

The pair is the honest-modeling test: the same sentence pattern has to resolve to an *event* in one case and a *state change on a different entity* in the other.

## Vocabulary bar

A spec at this caliber uses the drinker's own words, in the drinker's own sense:

| Term | What it must mean in the spec |
| --- | --- |
| dram | One pour, tasted at a time — the event entity, not the bottle |
| nose / palate / finish | Three distinct fields, not one blob of tasting text |
| peated | A malt characteristic of the bottling, not a flavor note on the pour |
| 12 year | An age statement on the bottle; absent means NAS, which is meaningful |
| neat / drop of water / rocks / highball | Serving style — the same bottle is a different dram each way |
| cask type | ex-bourbon, oloroso sherry, virgin oak — the main driver of flavor |
| ABV | Bottled strength as a percentage, constrained to physical limits |
| official / independent | Who bottled it; independents are a whole collecting axis |
| dunnage | The warehouse the visual world is named after, not a data field |

## What the spec commits to

- **Four entities with separate lifecycles.** `distillery` (canonical, including silent ones whose bottles outlive them), `bottle` (owned, sealed → open → finished → archived), `dram` (event), `flavor_note` (observation). Collapsing bottle and dram is the mistake that makes "two-thirds left" unfileable.
- **The palate map is earned, not decorative.** `flavor_note` rows are indexed by `descriptor` and `axis` so the recurrence workload ("which descriptors keep appearing in drams scored 85+") is a real query with a real index behind it.
- **A visual world for a dim room.** `dunnage-bench`: charred-oak darks, amber spirit accent, cool bottle-green counterpoint, a fill-level shelf rail and a tri-panel dram card. Explicitly avoids medal-and-badge gamification and stock barrel photography.

## Files

| Path | What it is |
| --- | --- |
| `spec.yaml` | The hand-authored FoundrySpec — the bar |
| `bundle/app.html` | Compiled application (deterministic, from the spec) |
| `bundle/schema.sql` | SQLite DDL with named CHECK constraints and workload indexes |
| `bundle/foundry-spec.json` | Normalized spec as compiled |
| `bundle/evidence.json` | Source and principle snapshot backing the design |
| `bundle/build-receipt.json` | Content-hashed build receipt |
| `bundle/README.md` | Generated bundle readme |

## Reproduce

```bash
domain-foundry foundry validate examples/showcase/whisky-tasting/spec.yaml
domain-foundry foundry build examples/showcase/whisky-tasting/spec.yaml \
  --output examples/showcase/whisky-tasting/bundle
```

Sources cited: `whiskybase` (domain exemplar, `reference_only` pending editorial review) plus the cross-cutting authoritative slate — PostgreSQL constraints, SQLite foreign keys and query planner, W3C PROV, GOV.UK design principles, WCAG 2.2, ARIA APG, and the UI remix paper.
