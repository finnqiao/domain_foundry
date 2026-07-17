# Evaluation replay

The eval framework makes routing and extraction quality **enforceable** rather
than aspirational. It is deterministic by default, so it runs on every PR
without spending tokens, and it fails loudly with a legible per-pack diff when
quality regresses.

## Cassettes: deterministic LLM replay

Every LLM interpretation in a test is keyed by a **normalized prompt hash** and
recorded to a cassette. Three modes:

| Mode | Behavior |
|---|---|
| `replay` (default) | Serve recorded responses. Fully deterministic, zero tokens. The PR gate. |
| `record` | Fill missing cassette entries from a live model. |
| `live` | Re-record and accumulate a **drift report** (recorded-vs-live diffs). Nightly. |

The bundled fixtures also replay against the deterministic **heuristic** inner
router, so the core routing gate needs no recorded LLM at all.

## Scoring

`domain-expert eval --full` produces overall and **per-pack scorecards**:

- **routing accuracy** — did the capture hit the right object/operation?
- **per-field precision / recall / F1** — were fields extracted correctly?
- **disposition accuracy** — auto_apply vs review vs confirm vs unfiled.
- **calibration curves** — do confidence buckets match observed correctness?

Scorecards serialize to a compact **committed baseline**
(`examples/synthetic/eval_baseline.json`). A fresh replay diffs against that
baseline; any per-pack regression fails the gate.

## The break-then-restore gate

The signature test: deliberately break a router heuristic on a branch and CI
fails with a per-pack line like `sourdough: routing_accuracy 0.886 -> …`, with
the drop **isolated to the offending pack**; restore the fixture and it goes
green again. This is the whole point — regressions are legible and localized.

## Release-blocking invariant: zero false-completed-actions

A **false-completed-action** is any negative/should-not-file case that produced
a real-domain `auto_apply`. The corpus holds this at **zero**, and the baseline
diff is release-blocking: an injected count of 1 fails the build. This is the
guardrail behind never-drop's inverse — the system must not silently *act* on
something it should have left alone.

## Curated contract cases

Alongside the corpus replay, five named invariants run as one self-contained
gate:

1. approval executes exactly once,
2. the never-drop ladder (applied / review / unfiled / ledger-only),
3. multi-domain fan-out,
4. idempotent re-capture,
5. projection convergence (kill-the-daemon recovery).

## CI wiring

- **PR gate** — deterministic corpus replay + contract cases + zero-regression /
  zero-false-completed-action diff vs the committed baseline; plus a frozen-clock
  audit (no `datetime.now()` outside the injectable clock provider).
- **Nightly** — the live-LLM job against a **pinned model**, uploading a drift
  report artifact and degrading gracefully without an API key.

See [`docs/PHASE_STATUS.md`](../PHASE_STATUS.md) for the recorded P7 evidence.
