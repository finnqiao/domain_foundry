# Per-Domain Agent Mesh — Design Spec

**Date:** 2026-07-20
**Status:** Design (pre-implementation). No code yet — this document is the plan to approve.
**Owner:** Finn
**Systems:** `hermes` (agent gateway) + `domain_foundry` (DomainForge substrate)

---

## 1. Problem statement (in your words, root-caused)

Two failures, two distinct single points of failure:

> "if I have an ongoing message, I can't send a message in another domain … I can't do any quizzes unless I finish previous conversations or log previous recipes."

**Root cause — head-of-line blocking.** Hermes-agent runs **one serial conversation session**. Every channel (Telegram/WhatsApp/CLI) funnels into a single agent loop that processes one turn at a time. While that turn is busy — logging a recipe, or stuck mid-wizard/mid-correction sub-mode — *every* other inbound message waits behind it, regardless of domain. Your Japanese quiz cannot start because the single pipe is occupied. Worse: a quiz is a **stateful, multi-turn, sometimes system-initiated** interaction, and the capture-first loop has no concept of an in-progress session at all.

> "if the gateway is down … I can't send a message in another domain."

**Root cause — a single always-on write gateway.** Every DomainForge tool (`domain_foundry_capture`, `_query`, `_correct`, …) POSTs to one FastAPI server at `127.0.0.1:8787`. That process is a hard dependency on the *write* path. If it's not running, unreachable, or restarting, **all domains go dark at once.**

**What's already right (and worth preserving):** DomainForge is cleanly decomposed at the *data* layer. Domains are declarative **packs** (`schema.yaml` / `routing.yaml` / `operations.yaml` / `projections.yaml` / `policy.yaml`), the write path is a `HarnessAPI` over `ledger.sqlite` + `domains.sqlite`, routing is a regex+LLM classifier per pack, and the LLM layer already has an offline `HeuristicProvider` fallback. The monolith is the **agent/gateway layer**, not the substrate. So we don't rebuild DomainForge — we put a *mesh of agents* on top of it and take the single gateway off the write path.

The client class is even already named for this: `DomainExpertClient`. Each per-domain agent is a **Domain Expert**.

---

## 2. Decisions locked (from review)

| Fork | Decision |
|---|---|
| Isolation model | **Long-lived per-domain agents.** Each domain is its own always-on service with its own inbox, loop, session state, and schedule. |
| Interactive/proactive | **Yes — first-class.** A domain can drive a session (Anki quiz, spaced repetition, coaching) and initiate contact on a schedule. |
| Gateway-down | **Designed out entirely.** No always-on network service on the write path. Agents embed the harness as a library and write straight to SQLite; the web/API server becomes an *optional reader*. "Gateway down" stops being a state the user can observe. |

---

## 3. Target architecture — the Domain Mesh

```
        Telegram   WhatsApp   CLI   Voice   Web        ← channels (Hermes-agent gateway ingests)
            │         │        │      │       │
            └─────────┴────┬───┴──────┴───────┘
                           ▼
                 ┌───────────────────┐
                 │     CONCIERGE     │   thin, per-message, NEVER blocks
                 │  (router/switch)  │   • durably journals every inbound msg FIRST
                 │                   │   • classifies domain (reuses routing.yaml)
                 │                   │   • sticky-routes to active session
                 │                   │   • multiplexes OUTBOUND (proactive msgs)
                 └───────┬───────────┘
          enqueue (SQLite, atomic)   │  ▲ outbound
        ┌──────────────┬─────────────┼──┴────────────┐
        ▼              ▼             ▼                ▼
  ┌──────────┐   ┌──────────┐  ┌──────────┐    ┌──────────┐
  │  FOOD    │   │ JAPANESE │  │  PLANTS  │ …  │ general  │   ← Domain Experts
  │  Expert  │   │  Expert  │  │  Expert  │    │  Expert  │     (N long-lived procs)
  │          │   │          │  │          │    │          │
  │ inbox Q  │   │ inbox Q  │  │ inbox Q  │    │ inbox Q  │   durable per-domain queue
  │ loop     │   │ loop     │  │ loop     │    │ loop     │   own LLM loop + tools
  │ session  │   │ session  │  │ session  │    │ session  │   own multi-turn state
  │ schedule │   │ schedule │  │ schedule │    │ schedule │   own cron/proactive triggers
  └────┬─────┘   └────┬─────┘  └────┬─────┘    └────┬─────┘
       │ embeds HarnessAPI (library, no HTTP hop)   │
       └──────────────┴──────────┬─────────────────┘
                                 ▼
                   ┌──────────────────────────┐
                   │   SUBSTRATE (shared)      │  ledger.sqlite + domains.sqlite
                   │   SQLite, WAL mode        │  single source of truth
                   │   idempotent apply        │
                   └──────────┬───────────────┘
                              │ read-only
                   ┌──────────▼───────────────┐
                   │  Web app / API (OPTIONAL) │  reader + UI only; off the write path
                   └──────────────────────────┘

        ┌──────────────────────────────────────────────────┐
        │  SUPERVISOR (launchd)  — starts/monitors/restarts │
        │  every Concierge + Domain Expert. Health & backpressure.
        └──────────────────────────────────────────────────┘
```

Five components. Three are new (**Concierge**, **Domain Expert** runtime, **Supervisor**); two exist and are reused (packs/HarnessAPI substrate, channels/gateway).

### 3.1 Concierge (the router / switchboard)
The one thing you "talk to." Holds **no domain business logic** and does **no LLM-heavy work** — its job is fast, bounded, and never blocks:

1. **Journal-first.** On every inbound message, append it to a durable append-only `inbox_journal` (SQLite) *before anything else*. This is capture-first moved down to the transport layer — the message is safe even if everything downstream is dead.
2. **Classify.** Reuse each pack's `routing.yaml` (regex + examples + `llm_hints`) to pick the target domain. This code already exists in DomainForge's router; the Concierge calls it.
3. **Sticky-route.** If a domain has an **active session** with the user (a quiz in progress), route there unless the user clearly switches (explicit domain mention, or the domain's Expert rejects the message as "not mine"). See §5.3.
4. **Enqueue.** Insert the message onto the target Domain Expert's durable inbox queue (atomic SQLite write) and return. Done — bounded time, no blocking on downstream processing.
5. **Multiplex outbound.** Domain Experts send *proactive* messages (a due-cards nudge) back through the Concierge, which owns the channel handles, tags the message with its origin domain, and routes the user's reply back to that domain.

Because the Concierge only journals + classifies + enqueues, a slow or hung Domain Expert can **never** stall it. That is the direct fix for "ongoing message blocks other domains."

### 3.2 Domain Expert (the per-domain agent)
One long-lived process per active domain. Fully defined by its **pack + `agent.yaml`** (§4). Each owns:

- **Durable inbox queue** — messages for its domain. Survives crashes; drained in order.
- **Its own agent loop** — LLM + the *subset* of tools this domain needs, plus domain-specific tools (e.g. `quiz_next`, `quiz_grade`). Processes its inbox **serially within the domain** (ordered, deterministic) while all other domains run **concurrently**.
- **Session state** — a multi-turn state machine (`domain_session` table). A quiz, a wizard, a multi-message correction lives here. Being mid-session blocks only *this* domain, never others.
- **Scheduler** — evaluates the pack's `schedules:` and can wake itself and **initiate** an outbound message (Anki review due, plant needs water). New capability; see §5.
- **Embedded HarnessAPI** — imported as a library. Writes go **straight to the ledger** via `apply` (idempotent), no HTTP hop. This is what removes the gateway from the write path.

### 3.3 Supervisor
A launchd-managed process manager (Mac-as-hub stays). Starts the Concierge + one Domain Expert per active domain, watches health, restarts on crash with backoff, and applies backpressure (if a queue is backing up, it can throttle intake or spin the Expert back up). Reuses the spirit of the existing Hermes `cron/jobs.json` health jobs. A crashed Domain Expert means its inbox *accumulates and drains on restart* — the user sees at worst a delayed reply, never a lost message and never "gateway down."

### 3.4 Substrate (reused, hardened)
`ledger.sqlite` + `domains.sqlite`, now in **WAL mode** with `busy_timeout`. Concurrency rules that keep N writers safe at personal scale:
- Each Domain Expert writes **only its own domain's rows** (natural partition — no two Experts contend for the same object).
- WAL permits many concurrent readers + one writer at a time; `busy_timeout=5000ms` makes the rare cross-domain write overlap *wait* rather than error.
- `apply` is already **idempotent** (idempotency keys / source_ref), so restart-redelivery is safe.
- The web/API server opens the DB **read-only**. It is never required for a write to succeed.

(Stricter option if contention ever shows up: funnel all writes through a single "ledger-writer" actor and let Experts submit write-intents to it. Not needed at current throughput; noted for scale.)

---

## 4. What defines an agent: `agent.yaml` (new, per pack)

Today a domain = a pack. We add one file so a domain also ships an **agent**. Creating a new per-domain agent = writing a pack + this manifest; nothing else.

```yaml
# packs/japanese/agent.yaml
agent:
  name: japanese
  persona: >
    You are the user's Japanese coach. You run spaced-repetition quizzes,
    log vocab/grammar they encounter, and track what's due for review.
  tools:                       # subset of harness tools + domain tools
    - capture
    - query
    - correct
    - quiz_next                # domain-specific (defined by the pack)
    - quiz_grade
  autonomy:                    # per-interaction policy (extends policy.yaml)
    capture: auto              # log vocab silently
    quiz:    interactive       # drive a multi-turn session
  sessions:                    # NEW: multi-turn state machines
    - id: quiz
      goal: "run a spaced-repetition review of due cards"
      state: {cards: [], index: 0, correct: 0}
      enter:
        - load: "SELECT * FROM jp_vocab WHERE next_review <= now() ORDER BY next_review LIMIT 20"
          into: cards
      turn: |
        Present cards[index]. Grade the user's answer with quiz_grade,
        update next_review (SM-2), advance index. End when index >= len(cards).
      exit:
        - summarize: "quizzed {correct}/{index} cards"
  schedules:                   # NEW: proactive triggers
    - id: daily_review
      cron: "0 9 * * *"
      when: "SELECT count(*) FROM jp_vocab WHERE next_review <= now()"   # >0 to fire
      action: start_session(quiz)
      message: "You have {count} Japanese cards due. Want to review now?"
```

- `sessions:` and `schedules:` are the **only genuinely new pack surface.** `persona`, `tools`, `autonomy` are thin wrappers over things that already exist (routing, policy matrix, tool set).
- `interpretation:` gains a third value **`interactive`** alongside `simple` / `structured`, signalling the Expert to run a session loop, not just a capture loop.
- The DomainForge **wizard** (`new_domain` / `wizard_reply`) is extended to scaffold `agent.yaml` too, so "stand up a new domain" produces a domain **and** its agent in one flow — matching your "an agent for every domain we create."

---

## 5. Interactive & proactive domains (the Anki fix)

### 5.1 Sessions
A `domain_session` row = `(domain, user, session_type, state_json, status, updated_at)`. The Expert's loop is:

```
on inbox message m:
    if active session s for (domain, user):
        interpret m as a TURN in s   ← not a capture
        advance s.state; persist
        if s complete: close, run exit
    else:
        classify m via routing.yaml; capture/correct/query as today
```

Because sessions are **per-domain and per-Expert**, being mid-quiz in `japanese` has zero effect on `food` — a different process with a different inbox. This is precisely "do a quiz without finishing the recipe log first."

### 5.2 Scheduler / proactive contact
Each Expert runs a lightweight scheduler over its pack's `schedules:`. A trigger is `cron` **and/or** a `when:` query against the domain's data (fire only if there's something to do). On fire → start a session and push an **outbound** message via the Concierge → channel. New behaviors this unlocks: Anki "cards due" nudges, plant-watering reminders, "you haven't logged a bake this week" prompts. The Hermes `cron` infrastructure is the model; this makes it *per-domain and data-driven* instead of global.

### 5.3 Stickiness, barge-in, and switching (the UX glue)
The Concierge keeps a small **routing context** per user: which domain (if any) holds an active session.
- **Sticky:** while a quiz is live, plain answers ("食べる", "B", "next") route to `japanese`.
- **Barge-in:** an unrelated capture ("cooked shoyu ramen, too salty") is classified by `routing.yaml` to `food`, enqueued to the **Food** Expert, and runs **concurrently** — the quiz stays alive. When you answer the quiz next, it's sticky-routed back to `japanese`.
- **Switch:** explicit intent ("stop the quiz", "actually, log a bake") ends/pauses the session and re-routes.
- **Reject:** if an Expert receives a message that clearly isn't its domain, it replies `not_mine` and the Concierge re-classifies — a cheap self-correcting fallback.

This is only possible *because* domains are independent processes; it's the payoff of the isolation decision.

---

## 6. "Never see gateway down again" — the durability ladder

A message is safe at every step; no single component's death blocks capture:

1. **Ingest → `inbox_journal`** (append-only SQLite) before any processing. Even if the Concierge crashes the instant after, the message is on disk.
2. **Enqueue → domain inbox** — atomic SQLite insert (WAL). Survives crash; redelivery is idempotent.
3. **Process** — the Expert reads from its durable queue, writes canonical rows via embedded `HarnessAPI`, and **acks only after the ledger commit**. Crash mid-process → message stays unacked → reprocessed on restart (idempotent apply makes this safe).
4. **Expert down** → inbox accumulates; Supervisor restarts; queue drains. User sees a *delayed* reply, never a lost one.
5. **Web/API server down** → **irrelevant.** It's a read-only reader. Writes never touched it.

There is no always-on network service on the write path, so "gateway down" is no longer an observable state. The worst degradation is latency, and latency self-heals on restart.

**Offline LLM degradation:** the existing `HeuristicProvider` means even with no API key / cost-guard tripped, capture-first routing still functions deterministically. Quizzes can fall back to non-LLM grading paths where the pack defines them.

---

## 7. Data model additions (small)

| Table | Purpose |
|---|---|
| `inbox_journal` | append-only record of every inbound message (transport-level capture-first) |
| `domain_inbox` | per-domain durable work queue: `(domain, msg_id, payload, status, enqueued_at, acked_at)` |
| `domain_session` | active multi-turn sessions: `(domain, user, session_type, state_json, status, updated_at)` |
| `schedule_run` | scheduler bookkeeping: last-fired / next-due per `(domain, schedule_id)` (idempotent, no double-fire) |
| `outbound_queue` | proactive messages awaiting delivery via the Concierge (durable, retried) |

All live in the existing SQLite substrate (WAL). No new datastore, no new service.

---

## 8. Concurrency invariants (the contract)

1. **Head-of-line isolation** — work in domain A never blocks domain B. (Separate processes + separate durable queues.)
2. **No lost input** — every inbound message is durably journaled *before* processing.
3. **No global write gateway** — any single component can die without blocking capture.
4. **Serial within a domain, concurrent across domains** — deterministic ordering per domain; parallelism across the mesh.
5. **Idempotent apply** — restart / redelivery / duplicate channel events are safe (reuses existing idempotency keys).
6. **Bounded Concierge** — routing a message is O(fast); it never awaits downstream processing.

---

## 9. Failure-mode table

| Failure | Old behavior | New behavior |
|---|---|---|
| Long turn in domain A | All other domains blocked | A's Expert busy; B/C/D fully responsive |
| Mid-quiz, want to log a recipe | Impossible until quiz ends | Recipe routes to Food Expert concurrently; quiz stays live |
| Write gateway (8787) down | All capture fails | No effect — writes are in-process to SQLite |
| Domain Expert crashes | (n/a) | Inbox accumulates; Supervisor restarts; drains; nothing lost |
| DB write overlap | (rare) error | `busy_timeout` waits; per-domain partition avoids most contention |
| Ambiguous routing | Misfiled silently | Concierge disambiguates or routes to `general`; Expert can `not_mine`-reject |
| Duplicate channel delivery | Possible double-write | Idempotent apply dedupes |
| Mac asleep / restart | Session lost | Durable queues + sessions rehydrate on wake |

---

## 10. Phased migration (each phase independently shippable & green)

- **P0 — De-SPOF the write path.** Switch ledger to WAL; make Domain Experts (and the CLI) embed `HarnessAPI` directly instead of POSTing to 8787. Web/API opens read-only. *Exit:* kill the FastAPI server and confirm CLI capture still works.
- **P1 — Concierge + Supervisor + two Experts.** Extract the router into a Concierge with `inbox_journal` + `domain_inbox`. Run `food` and `japanese` as two long-lived Experts under launchd. *Exit:* a long-running Food turn does not delay a Japanese capture (prove head-of-line isolation with a timing test).
- **P2 — Sessions + scheduler.** Add `domain_session`, `schedule_run`, `outbound_queue`, `interpretation: interactive`, and the `sessions:`/`schedules:` pack surface. Build the `japanese` quiz pack (SM-2 over existing `jp_vocab`/`jp_grammar`). *Exit:* a scheduled 9am quiz fires proactively and runs to completion while a recipe is logged mid-quiz.
- **P3 — Concierge UX glue.** Stickiness, barge-in, switch/`not_mine` re-routing, outbound multiplexing with origin tagging. *Exit:* interleave quiz answers and food logs in one channel without cross-talk.
- **P4 — Wizard scaffolds agents.** Extend `new_domain` to emit `agent.yaml`; migrate remaining domains (plants, sourdough, travel) onto the mesh. *Exit:* "create a dive-log domain" produces a pack **and** a running Expert.
- **P5 — Observability & hardening.** Per-domain health, queue-depth metrics, dead-letter for poison messages, backpressure tuning. Web app becomes a pure read-only mesh dashboard.

---

## 11. Open decisions (need a call before P2/P4)

1. **Session persistence granularity** — snapshot `state_json` every turn (simple, safe) vs. event-source turns (replayable, more work). Recommend snapshot for v1.
2. **Expert lifecycle** — always-on for *all* active domains (simplest, matches decision) vs. lazy-start rarely-used domains on first message and idle them out (lighter Mac footprint). Recommend always-on for the 3–4 daily domains, lazy for the long tail.
3. **Concierge classifier cost** — regex-only fast path with LLM disambiguation only on low-confidence (cheap) vs. always-LLM (accurate, pricier). Recommend regex-first + LLM tiebreak (mirrors current router).
4. **Quiz scheduling algorithm** — SM-2 (Anki-classic) vs. FSRS (modern, better retention). Recommend SM-2 for v1, FSRS as a pack-config option later.

---

## 12. Why this is the right shape

- It **reuses** DomainForge's real strength (declarative packs + idempotent SQLite apply) and only rebuilds the layer that's actually monolithic (the single agent + single gateway).
- It maps **one-to-one** to your two complaints: isolation kills head-of-line blocking; embedding the harness kills "gateway down."
- It makes "**an agent for every domain**" a first-class, low-cost act: a pack + one `agent.yaml`, scaffolded by the existing wizard.
- It adds the **interactive/proactive** capability the Anki example actually requires — sessions + a per-domain, data-driven scheduler — without bolting a second system alongside DomainForge.
```
