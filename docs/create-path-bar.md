# The create-path bar

The bar for the create path, set deliberately before the work that has to reach it.

Every artifact here is labeled with how it was made. Nothing on this page is output
from the live research pipeline yet; saying otherwise would break the rule in
`DESIGN.md` about never calling a scaffold researched.

## Why this exists

The 50-interest audit of 2026-08-23 measured the create path at **28/50 full passes**.
The failures were not random. Six goals snapped to an unrelated neighborhood because a
single weak token scored (whisky to Dev Notes, vinyl and chess to soccer, model trains
to freediving, aquarium to a scuba pokedex, yoga to instrument practice). Sixteen more
forked correctly and then died on the first real sentence the user typed, because the
compiled pack carried no domain vocabulary.

These artifacts define what "fixed" looks like, in enough detail to be measured against.

### Where the create path stands

Measured by the committed interest suite (offline, deterministic, per-case ratchet):

| | audit | now |
|---|---|---|
| full passes | 28 / 50 | **50 / 50** |
| snapped to a wrong neighborhood | 6 | **0** |
| first capture failed | 16 | **0** |
| indexed hobbies | 24 / 30 | **30 / 30** |
| collision cases | 4 / 10 | **10 / 10** |
| unindexed hobbies | 3 / 10 | **10 / 10** |

Read `pass` beside the suite's `held_out` figure. `pass` is measured against a
probe the seed author could see, and each late-passing case turns on one shared
word. `held_out` replays a sentence the design never saw, and offline it is
**0/10**: one user sentence teaches a pack the words in that sentence and nothing
else. That is the honest ceiling of a keyword scaffold, and it is what
research-backed generation exists to lift.

The bridge in [ADR-010](adr/ADR-010-wizard-foundry-bridge.md) is now wired: with a
reasoning model configured, an unindexed or thin goal escalates into the Foundry
pipeline, and the resulting spec is projected into the same runtime the wizard
already uses. Offline the bridge is inert, which is why the suite is unchanged.

## Create-flow prototypes

Hand-authored HTML mockups of the flow a person actually walks through. They are the
visual contract for the phases that follow.

| Prototype | What it shows |
|---|---|
| [Before](prototypes/create-flow/before.html) | What "whisky tasting notes" gets today, replayed verbatim from audit row 32: a snap to Dev Notes, then a first capture that dies unfiled at 0.2 confidence |
| [Ideal, keyed](prototypes/create-flow/ideal-create.html) | An honest "I don't know whisky", two elicited sentences, a cited research receipt, three structurally different cuts, a domain look, and a first capture that files at 86% |
| [Fallback, keyless](prototypes/create-flow/fallback-create.html) | Demo mode naming its own ceiling in the user's language, building from their words, still filing, and showing concretely what a key would add |

Each page carries a `hand-authored mockup` banner and a direction contract in its
opening HTML comment.

## Showcase targets

Five interests, each a hand-authored `FoundrySpec` at golden caliber plus a bundle
**compiled from that spec by the real deterministic `FoundryCompiler`**. No live model
touched the bundles; `foundry build` is pure compilation.

The specs are the bar. The program is finished when the live pipeline produces specs of
this caliber unaided, and the diff against these targets is the acceptance test.

| Interest | Why it's here | Target |
|---|---|---|
| Whisky tasting | Snaps to `making.dev` today because `notes` scored | `examples/showcase/whisky-tasting/` |
| LEGO builds | Unindexed; currently gets `Lego shelf / timeline / chart` | `examples/showcase/lego-builds/` |
| Lifting log | Forks correctly and still cannot file `squat 5x5 at 100kg` | `examples/showcase/lifting-log/` |
| Ham radio | Unindexed; `QSO`, `RST`, and `QSL` are invisible to the compiler | `examples/showcase/ham-radio/` |
| Aquarium | Snaps to a scuba species pokedex today | `examples/showcase/aquarium/` |

Each showcase README states its **acceptance utterances**: the sentences the finished
pipeline's app must file without a second pass. Those sentences are the measurable
version of "the magic worked".

```text
whisky     peated dram, iodine and orchard fruit, 12 year, neat
lego       finished the Millennium Falcon MOC, 3800 pieces, missing 2 tiles
lifting    squat 5x5 at 100kg, last set was a grind
ham radio  worked JA1RQK on 20 meters, RST 59, QSL via bureau
aquarium   added a neon tetra, parameters 6.8 pH, 78F, new plant
```

### Rebuilding a bundle

```bash
domain-foundry foundry validate examples/showcase/whisky-tasting/spec.yaml
domain-foundry foundry build examples/showcase/whisky-tasting/spec.yaml \
  --output examples/showcase/whisky-tasting/bundle
```

`foundry build` refuses to overwrite a populated directory, so build to a fresh path
when regenerating.

## Reviewed goldens

The three manually authored specifications that predate this work, used as projection
fixtures, live under `examples/golden/`: Sourdough Lab, Card Collector, and Japanese
Study Coach.

### Regenerating through the live pipeline

`scripts/build_showcase.py` asks the real pipeline to produce each target for itself
and writes the result to `examples/showcase/<interest>/generated/`, beside the
hand-authored target. The diff between the two is the acceptance test for this whole
programme.

```bash
python scripts/build_showcase.py --list
python scripts/build_showcase.py --all
```

It reuses each target's own `authored_by: user` acceptance cases as the run's judge,
so the generator still never authors its own criteria. It fails closed without a
configured reasoning model: generating a showcase from the offline keyword scaffold
would file an unresearched artifact under a "generated" label.

## What is not here yet

- Bundles generated end to end by the live keyed pipeline from a plain sentence. The
  script above is ready; running it needs a configured provider, which is a human
  gate. When it lands, generated output sits beside each hand-authored target with
  its receipts, and the diff is reviewable.
- Independent editorial review of the knowledge corpus. The five domain-exemplar
  sources added for these showcases are `reference_only` and say so.
