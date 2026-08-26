# Universal create prototype notes

> Throwaway prototype. Delete or absorb it after the creation-flow decision.

## The question

How should a non-technical hobbyist move from a vague or specific interest to a
researched personal app without seeing the compiler, schema, or routing machinery?

The prototype lives in `release-create.html`. Switch layouts with
`?variant=A`, `?variant=B`, or `?variant=C`. Switch scenarios inside the page.

## The three layouts

| Variant | Structure | Strength | Cost |
| --- | --- | --- | --- |
| **A — Guided** | One current decision, a persistent build rail, and a compact proof panel | Makes the next action obvious and keeps evidence close without turning the journey into a technical workbench | Uses more screen structure than a chat transcript |
| **B — Conversation** | A plain-language transcript beside the app taking shape | Feels familiar and preserves conversational corrections | Risks returning to a question-and-answer product |
| **C — App first** | The emerging app dominates; each decision appears in a dock below it | Makes the product payoff immediate | Gives research and model decisions less room |

## Recommended direction

Use **Variant A — Guided** for the release path. Borrow the live app pane
from Variant C for the concept and proof stages. Keep Variant B only as a narrow
mobile or chat-adapter rendering, not as the web information architecture.

This recommendation is provisional until a maintainer and three external users
complete the broad, specific, obscure, and no-key scenarios without coaching.

## Voice direction

Domain Foundry should sound like a capable guide, not an AI narrator. Its voice
is calm, clear, and quietly encouraging. It speaks about the person’s interest
and next choice. It does not narrate prompts, models, routing, or compilation in
the main journey.

“Soft” does not mean vague, chatty, or full of apologies. It means that the
interface explains why it asks, uses familiar words, and gives a useful next
step. Trust still comes from specific facts, with technical evidence available
under **How this was checked** or **See technical details**.

### Writing rules

- **Begin with the activity.** Ask “What would you like to do with whisky?”
  rather than asking the person to classify their interest.
- **Ask one thing at a time.** Every screen has one main decision, a clear Back
  action, and one primary way to continue.
- **Use practice language.** Say “bottles and tastings,” not “objects and
  relationships.” Repeat the person’s own terms when they are clear.
- **Describe real progress.** Name the current task and finished stages. Show an
  elapsed time, but do not invent a percentage or completion estimate.
- **Keep limits calm.** Say what works now, what is missing, and what can happen
  next. Do not call the experience “degraded,” “thin,” or a “scaffold.”
- **Put recovery beside the problem.** Preserve every answer. Explain the next
  safe action without blame, jokes, or a generic “Something went wrong.”
- **Use one product voice.** Prefer neutral status phrases such as “Looking at
  sourdough practice” over a character-like “I am researching your domain.”
- **Show understanding.** Present an editable summary instead of saying “I
  understand.” Say “closest to what you described” instead of “AI recommended.”
- **Avoid empty reassurance.** Do not call a task easy, smart, magical, or
  foolproof. Reassure with saved work, clear limits, and a way forward.

### Vocabulary for the main journey

| Internal term | Main-journey wording | Optional detail wording |
| --- | --- | --- |
| practice classification | what you want to do | practice summary |
| evidence tier | based on | source type and provider |
| held-out example | second note | final check kept separate from design |
| routing | went to the right place | filed as, confidence, receipt ID |
| schema or model | what the app keeps track of | records, fields, relationships |
| compiler or artifact | building the app | build version and file hash |
| artifact identity | preview and export match | matching file hashes |
| personal draft | built from your notes | no reviewed sources used |
| model key missing | research is not available | provider setup and failure reason |
| provenance | edit history; how this was made | source and revision records |

### Tone by moment

| Moment | Tone | Example |
| --- | --- | --- |
| Start | Open and low pressure | “A topic is enough.” |
| Narrowing | Curious and concrete | “What would you like to do with whisky?” |
| Long wait | Calm and factual | “Comparing useful daily routines · 18 s” |
| Unavailable research | Direct and useful | “Research is not available right now. You can continue with your notes.” |
| Check failed | Serious and recoverable | “Your note was not saved. It is still here to edit or copy.” |
| Success | Warm but restrained | “Your first tasting is saved.” |

### Reusable recovery patterns

| Situation | Suggested wording |
| --- | --- |
| The interest is unclear | “There are a few possible directions. Add one note you might write, or choose a direction below.” |
| Research stops | “Research stopped before it finished. Your choices are saved. Try again, change your setup, or continue with your notes.” |
| The app cannot be built | “Tasting Bench could not be built yet. Your choices are saved. Try again or see what stopped the build.” |
| The second note goes elsewhere | “Your second note went to Bottle, but it may belong under Tasting. Choose the right place before you continue.” |
| A real note does not save | “Your note was not saved. It is still here to edit or copy.” |
| The result is uncertain | “This looks like a tasting. Check it before saving.” |

## Research behind the voice

The direction above draws from first-party content and design guidance reviewed
on 25 August 2026:

- [NHS: Think of the form as a conversation](https://service-manual.nhs.uk/content/how-to-write-good-questions-for-forms/think-of-the-form-as-a-conversation)
  recommends familiar language, softer phrasing, and reading questions aloud.
- [Microsoft: Simple and human voice](https://learn.microsoft.com/en-us/style-guide/brand-voice-above-all-simple-human)
  balances warmth with crisp, clear next steps and layered detail.
- [GOV.UK: Question pages](https://design-system.service.gov.uk/patterns/question-pages/)
  recommends one question at a time, asking only for needed information, and
  keeping Back available.
- [Carbon: Loading](https://carbondesignsystem.com/patterns/loading-pattern/)
  recommends visible progress for work that lasts more than a moment and status
  announcements for assistive technology.
- [Apple: Writing](https://developer.apple.com/design/human-interface-guidelines/writing)
  recommends familiar vocabulary, action-led labels, consistent flow language,
  and technical detail only where it helps.
- [GOV.UK: Error messages](https://design-system.service.gov.uk/components/error-message/)
  recommends specific recovery text beside the problem while preserving the
  person’s existing answers.

## Decisions the prototype tests

- **Broad interests narrow first.** “Whisky” becomes a choice between tasting,
  collecting, learning, making drinks, or a user-written alternative.
- **Specific interests move faster.** A precise goal gets one editable practice
  summary rather than the full narrowing step.
- **Examples replace technical tasks.** Two real sentences shape the app and
  check the result without asking the person to design a test.
- **Research is visible but quiet.** The main panel names the current activity.
  Source, cost, and provider details stay in the proof panel.
- **Concepts are product choices.** Cards compare daily loop, payoff, and
  trade-off. They do not expose schema identifiers.
- **The model is explained in domain language.** Example records and questions
  appear first. JSON and SQL sit behind “See technical details.”
- **Ready has a strict meaning.** The second note goes to the right place, the
  preview matches the export, and one real note saves before the app is ready.

## Cleanup rule

After selection, rewrite the winning layout in production components. Do not
promote this static file directly. Delete the losing layouts and this switcher.
