# Copy rules

Every word a person reads follows these six rules. That means the CLI, the
studio, the README, and the pages under `docs/` that a user opens.
`scripts/claims_audit.py --check copy` enforces the two rules a machine can
check. The other four are on the person writing and the person reviewing.

If you only remember one thing: write the way you would talk to a friend who is
not an engineer, and say the point first.

## 1. Plain conversational language, the point first

Say what happens, then why. No jargon, no nouns stacked three deep.

| Instead of | Write |
|---|---|
| Evidence to concepts to schema to experience to owned app, one inspectable specification. | It reads up on your interest, offers three ways to build it, then builds the one you pick. You can open every step. |
| Deterministic projection of the FoundrySpec onto the shortlist model. | The plan you approved is what gets built. |
| Bounded live discovery grounds domain vocabulary. | It looks up a few pages about your interest first, so it uses your words and not generic ones. |

## 2. No em dashes

Use a full stop, a comma, or two sentences. An em dash usually hides a sentence
that wanted to be two.

The left column below writes the dash as `&mdash;`, because this page has to
pass its own rule.

| Instead of | Write |
|---|---|
| Pick a look &mdash; then build it. | Pick a look, then say build it. |
| Your sources are never written to &mdash; databases are opened read only. | Your sources are never written to. Databases are opened read only. |
| One spec, one product &mdash; preview, schema, app, and receipt. | One spec builds the whole thing: the preview, the schema, the app, and the receipt. |

## 3. Never mention money

No costs, no prices, no "free", no paid upgrades. The defaults work. If someone
asks about a paid option, answer then, not before.

| Instead of | Write |
|---|---|
| Free and open source, no subscription. | Open source, and it runs on your machine. |
| Upgrade for unlimited apps. | Build as many as you like. |
| The free tier covers most people. | This covers most people. |

"Free-text notes" and "secrets-free export" are about text and secrets, not
money, and are fine.

## 4. No clever lines

No poetry, no metaphors doing work a plain sentence should do. The canonical
failure is "the page you'd open to settle an argument". Nobody knows what that
builds.

| Instead of | Write |
|---|---|
| The page you'd open to settle an argument. | A page that shows two of your records side by side. |
| Your interest, forged. | The app you asked for, built and on your machine. |
| Three cuts. | Three ways to build this. |

## 5. Every ask names exactly what to provide

Never ask for "sources", "data", or "some context". Name the actual things a
person has.

| Instead of | Write |
|---|---|
| Add sources. | Point me at a spreadsheet you keep, a notes folder, photos, an export from another app or your email. |
| Provide reference material. | One or two pages you trust, like a field guide or a species checklist. |
| Describe your constraints. | Tell me anything it has to do. For example: works with no signal, quick to log on a phone. |

The canonical seed ask, for whatever asks a person for their records:

> Point me at anything you already keep: a spreadsheet, a notes folder, photos,
> an export from another app or your email. If you have one or two pages you
> trust, like a field guide or a species checklist, those help too.

## 6. Pitch an idea the way a friend would

One line about what you already have. One line about what it becomes. One line
about how it feels. The engineering spec stays available underneath. It is
never the pitch.

The template:

> Want to log every nudibranch you see? You already have a log of observations
> and dates. Build a Pokedex-style tracker for it.

Two more:

> Want to know which bakes actually rise? You already write down the flour, the
> water, and the time. Build a side-by-side comparison for it.

> Want to see where your trail maps overlap? You already have the scans and the
> years. Build a map you can scrub through by decade.

Then, and only then, one line about design and feel: "Quiet, paper coloured, one
photo per row." Anything longer belongs in the spec.

## What the audit checks

`python scripts/claims_audit.py --check copy` fails on em dashes, on money
words, and on prices, across the user-facing pages and the string literals of
the CLI. A page that is not swept yet sits in
`scripts/claims_audit_allowlist.yaml` with the lane that will sweep it. That
list is meant to reach zero.
