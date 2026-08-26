# The interest suite

Fifty passions, each run end to end: type the goal, take the offered idea, build
it, then say one real domain sentence and see whether it lands.

Every other eval in this repository scores a pack that already exists. This one
scores the act of creation. A pack that compiles cleanly, validates, and cannot
file its owner's first sentence has not created anything.

## Running it

```bash
domain-foundry eval interest-suite                      # full run + ratchet
domain-foundry eval interest-suite --bucket unindexed   # one bucket
domain-foundry eval interest-suite --report /tmp/r.json # per-case detail
domain-foundry eval interest-suite --update-baseline    # re-pin, review the diff
```

Offline and deterministic: the heuristic provider, one throwaway workspace per
case, no key and no network. A full run takes about four minutes.

## What a case looks like

```json
{"id": "11_lifting", "bucket": "indexed", "goal": "log my gym lifting program",
 "accept": ["sports.strength"], "forbid": [], "unindexed_ok": false,
 "jargon": "squat 5x5 at 100kg, last set was a grind"}
```

`accept` and `forbid` are prefixes matched against the atlas cursor. `forbid` is
checked first: a confidently wrong app misleads a user more than an honest miss,
so a false snap outranks every other failure.

`goal`, `accept`, `forbid`, `bucket` and `jargon` are the yardstick. Editing one
to make a case pass is not a fix, it is a shorter ruler.

### `seed` / `seed2` — playing the elicitation turns

An unindexed goal now gets asked for two sentences in the user's own words
before anything is designed (ADR-010). A case answers with `seed` and `seed2`:

```json
{"id": "47_pottery", "bucket": "unindexed", "goal": "pottery wheel throwing",
 "jargon": "threw three bowls, trimmed the feet, bisque next week",
 "seed": "centered 2kg of stoneware and threw a tall vase",
 "seed2": "glazed the mugs in celadon and loaded the kiln"}
```

`seed` shapes the design. `seed2` is the wizard's *own* held-out check, replayed
through the real router after activation — deliberately not the same thing as
`jargon`, which stays the suite's independent yardstick and never enters the
create loop at all.

A case with no seed answers "skip", which is the honest fallback to the
pre-elicitation behaviour. `50_nonsense` has none on purpose: it is the suite's
coverage of the skip path.

Three buckets:

- **indexed** (30): the atlas should know this. Landing elsewhere is a miss.
- **collision** (10): two plausible neighbourhoods compete. `pokedex of my cards`
  belongs to collecting, not to a dive-species dex.
- **unindexed** (10): the atlas genuinely has no home. The only honest answer is
  to say so and invent from the user's words; `accept` is empty and `forbid`
  names the neighbourhoods it must not snap to.

## Verdicts

Worst to best, so the ordering doubles as the ratchet's comparison operator:

| Verdict | Meaning |
|---|---|
| `error` | The case crashed |
| `fail_snap` | Landed in a forbidden neighbourhood: a confident, wrong app |
| `fail_wrong_place` | Landed somewhere unaccepted, or missed an indexed goal |
| `fail_loop` | Right neighbourhood, but the first real sentence did not file |
| `pass_with_gap` | Filed the sentence, but also filed idle chatter |
| `pass` | Filed the sentence, ignored the chatter |

Each run also records quality dimensions that do not yet gate: field specificity
(how much of the built schema is about the interest rather than about logging),
look model and any fallback reason, and `jargon_swallowed` — true when the wizard
routed *nothing at all* for the user's sentence, as opposed to routing it and
filing it badly. Those are distinct failures with distinct fixes.

### Read `pass` next to `held_out`

Every run reports a `held_out` block, and it is the honest companion to `pass`.

At the time of writing the suite is **50/50 on `pass` and 0/10 on `held_out`**.
Both numbers are true and they measure different things.

`jargon` is a probe a human wrote knowing the hobby. The `seed` that shapes the
design was authored later, by someone who could see that probe — and the newly
passing cases each hang on a *single* shared content word (`inked`, `threw`,
`move`, `pieces`, `hive`). That is not fraud; it is how the mechanism genuinely
works, since a person's second sentence about their hobby usually does share a
word with their first. But it means `pass` is measured on a partly contaminated
yardstick and reads higher than the capability behind it.

`held_out` is the wizard's own second utterance, replayed after activation and
never seen by the design. It is uncontaminated, and offline it is zero — no
keyword scaffold learns a hobby from one sentence.

**`held_out` is the number research-backed generation has to move.** Treat a rise
in `pass` with a flat `held_out` as vocabulary luck, not understanding.

## The protected held-out set

`interest_suite_heldout.jsonl` is twenty more passions in the same schema, and
it exists because everything above admits the visible fifty can be improved by
writing better seeds. Nothing stopped that. This set is the stop.

It was authored from real hobbyist phrasing — homebrewing, 3D printing, bonsai,
board-game plays, quilting, genealogy, rock tumbling, orchids, fly tying, metal
detecting, kombucha, a birding big year, embroidery, bike maintenance, mushroom
foraging, calligraphy, terrariums, watches, sea glass, dog training — and never
from the atlas. No `seed` shares a content word with its own `jargon` probe, so
the shortcut the visible suite leans on is not available here.

```bash
domain-foundry eval interest-suite --cases examples/heldout/interest_suite_heldout.jsonl
python scripts/heldout_leakcheck.py          # the gate
python scripts/heldout_leakcheck.py --json   # machine output
```

The pass rate is **0/20**, and that is the honest reading, not a bug to hide.
Fourteen of the twenty reach a sensible neighbourhood, build a pack, and then
file the owner's first real sentence as `_unfiled` at 0.20 confidence: the
compiled routing rules and a practitioner's vocabulary do not intersect. Field
specificity is 0.0 on all twenty. The other six never get that far — a single
shared word in the goal drags them somewhere confident and wrong ("homebrew" to
`food.coffee`, "quilting projects" to `sports.climbing`, "embroidery … finish"
to `food.drinks`). Both halves are the same missing capability: nothing here
learns a hobby's words, so it can only match words it was already given.

**Its score does not gate.** Pinning 0/20 today would be trivially satisfied,
and pinning anything higher would block on the very gap the set exists to
reveal. It is a diagnostic. `scripts/heldout_leakcheck.py` is the gate.

### If the held-out set fails, improve the compiler — not the atlas

A held-out miss is a compiler bug. Adding an atlas node, alias, or vocabulary
entry because a held-out goal missed is exactly the behaviour the leak check
exists to catch, and it will fail the build naming the token, the file, and the
node. The same applies to the visible suite's text: the two sets stop measuring
different things the moment they share vocabulary.

The check reports four things, all fatal:

| Finding | What happened |
|---|---|
| `atlas_leak` | A held-out probe word is now in an atlas node's routing surface |
| `suite_leak` | A held-out probe word is now in the visible suite |
| `seed_overlap` | A held-out `seed` shares a content word with its own `jargon` |
| `goal_indexed` | A held-out *goal* word newly appeared in the atlas |

Goals are routing keys, so they are allowed to overlap the atlas — that is what
`indexed` and `collision` mean — and `goal_indexed` is therefore a ratchet
against the echoes that existed on the day the set was written, not a ban.
Words every hobby shares (`photos`, `session`, `notes`, times of day) sit in an
allowlist in the script; each entry carries its reason, and the reason has to be
"this word is generic", never "this word made the check fail".

## The ratchet

`interest_suite_baseline.json` pins a verdict per case. A run fails if any single
case ends worse than pinned, even when the total improves. Aggregate counts hide
trades: a change that fixes three goals and breaks one still reads as progress in
a summary and as a regression here.

Improvements never fail. Re-pin deliberately with `--update-baseline` and review
the diff as part of the change that earned it.

## A shortcut we measured and turned down

Two failing cases (`44_chess`, `43_fountainpens`) miss only because `\bplay\b`
does not match "played" and `\bink\b` does not match "inked". Adding a trailing
`(?:ed|ing|s)?` to single-word alphabetic rule terms was simulated in full: it
would take exactly those two cases and reach 45/50, with no new idle-chatter
matches and no bundled pack newly matching its own negative examples.

It was declined anyway. The dev pack's `\bpattern\b` widens to `patterns`, which
collides with the japanese pack's own example text; a clean single-pack L1 match
becomes `multi_pack`, dropping confidence from 0.85+ to 0.5 and escalating to L2.
That is not a wrong answer, but it is a routing-quality regression whose blast
radius grows with every pack a user installs — traded for two cases on a
yardstick, when the same two cases are what research-backed generation fixes
properly.

The real version of this idea needs a definition of "verb-like" (`pattern`,
`session`, and `decision` are nouns), which is its own piece of work rather than
a suffix heuristic.

## Provenance

Reconstructed 2026-08-23 from the 50-interest audit report, after the original
scratch harness was lost with its `/tmp` directory. The goals, buckets, and
jargon probes come from that report. `accept` and `forbid` encode the report's
own verdicts, so a neighbourhood it judged wrong is forbidden here rather than
blessed by the behaviour that produced it.

The reconstruction reproduces the report case for case, 49 of 50. The exception
is `39_yoga`: the report called it a wrong neighbourhood, this suite calls it a
false snap, because landing yoga on instrument practice is exactly the confident
wrongness `forbid` exists to catch. Same behaviour, sharper label.

Pinned baseline at reconstruction: **28 pass, 16 fail_loop, 6 fail_snap.**
