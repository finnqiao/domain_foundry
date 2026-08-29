# The trait graph

The idea atlas answers "where does this hobby live". The trait graph answers a
different question: "what is this hobby like, and what should the app be shaped
like because of it".

They are kept apart on purpose. A hobby the atlas has never heard of still has
traits. Traits are what let one sentence about tidepooling turn into three app
ideas that are genuinely different, instead of three names for the same log.

The rules live in `core/domain_foundry_core/atlas/trait_edges.yaml`. The code
that loads and applies them is `core/domain_foundry_core/atlas/traits.py`.

## Two kinds of edge

**Authored** edges are the rules. They are written by hand, they cite evidence,
and they never change because of a build. Each one says a trait of a practice
and the structural consequence of that trait.

**Detected** edges are what one particular brief and one particular set of
seeds turned out to match. Each one names the authored rule it fired and, when a
seed is what triggered it, the seed it was read off. So the reasoning is always
checkable: you can ask why the app came out session-shaped and get an answer
that points at a column in your own spreadsheet.

`TraitEdge` in `foundry/models.py` enforces the split. An authored edge with no
citation will not validate. Neither will a detected edge that names nothing.

## What each rule cites, and why

The citations are principle ids from `principles/` and source ids from
`source-registry.yaml`.

| Rule | Consequence | Cites | Why those |
|---|---|---|---|
| `cycle_driven` | Time windows come first | `UX-09`, `UX-01` | UX-09 says context decides layout, and a practice gated by the tide has its context set for it. UX-01 says start from what the person actually does, which here is checking whether they can go at all. |
| `collected_instances` | Catalog split into owned and missing | `rebrickable_api`, `pokemon_tcg_api`, `UX-05` | Both exemplars model a known finite set against what one person holds, which is exactly the owned-versus-gap split. UX-05 says each domain gets its own task topology. |
| `practiced_skill` | One session, one decision at a time | `anki_scheduler`, `fsrs4anki`, `UX-10` | Both exemplars are scheduling systems whose whole design is presenting one item at a time and asking one question about it. UX-10 says the first useful act beats configuration. |
| `place_bound` | Per-place history | `UX-09`, `UX-05` | Same reasoning as `cycle_driven` on context, applied to space instead of time. UX-05 keeps the topology domain-specific rather than uniform. |
| `produces_artifacts` | A roll reviewed a batch at a time | `UX-04`, `UX-06` | UX-04 says the preview is the contract, which matters most where the output is visual. UX-06 requires complete task states, and a review pass is where empty, partial and populated all show up at once. |
| `improves_over_time` | Record, compare, decide | `wger_workout`, `UX-08` | wger models progression against past records as the primary loop. UX-08 says trust is visible at the moment of consequence, which for a trend is the comparison itself. |

These are `domain_exemplar` and `product_reference` sources, so they are
reference-only. They support a design pattern being reasonable; none of them
endorses this project or any app it builds.

## How detection works

Each rule carries `signals`: words and column names. Signals are not evidence.
They decide what gets noticed; they never invent a consequence, because the
consequence is fixed by the rule.

A column outweighs a word. A `tide_height_m` column in someone's spreadsheet is
worth more than the word "tide" in a sentence, because they have been recording
it for a year. So a single matching column fires a rule on its own, while loose
words have to agree with each other before anything fires. One stray word is a
coincidence, and a coincidence is not a trait.

## Adding your own rules

Put a `trait_edges.yaml` in `~/.domain_foundry/atlas/`. It merges over the
shipped file, same id wins, the same way the idea atlas overlay does. Nothing
leaves your machine and nothing is uploaded.

If you want a rule to go the other way, into the shipped file that everyone
gets, that stays an editorial decision made by a person, the same as adding a
source to the registry. A rule is a claim about how a practice works, and claims
get read before they ship.

## What can and cannot be shared

A learned trait rule is a shape, so it can travel: "driven by the moon, then
time windows" says nothing about anyone's records. What was detected off a
personal upload is a different matter. The seed ids on a detected edge point at
the user's own files and stay local, along with everything in them.

Shapes and public links can travel. Your records never do.
