# Paid-provider admission: review and activation notes

This change adds atomic **local estimated-cost enforcement**, not a provider-account hard cap or a guaranteed dollar ceiling. Review pricing and account-level controls independently before enabling paid use.

## Behavior

- Each paid LLM HTTP attempt reserves against the shared workspace SQLite ledger before dispatch, after the final body is formed. Retries need a new reservation. Stricter caller limits and the requested policy tier are preserved through provider fallback.
- Admission includes settled spend for the current day and all outstanding holds across dates. Restart, midnight, changed caps, and unattributed legacy tiers cannot silently discard liability. Individual corrupt, negative or nonfinite ledger values fail closed.
- Only reviewed exact model/provider/dialect/endpoint combinations and bounded text-generation payloads are accepted. Unknown pricing, unsupported custom endpoints/features, malformed output ceilings, and missing migrations deny paid dispatch.
- Valid usage settles before generated JSON/schema/refusal handling. Missing or malformed usage, HTTP/network ambiguity, or a failed settlement keeps the hold. A measured estimate overrun persistently blocks further admission pending explicit reconciliation.
- Live accounted usage is not recorded twice by downstream callers. Cassette replay has zero current billed cost; a live cassette miss still uses admission. Foundry observation totals remain available without duplicate cost rows.
- **Paid Brave search is disabled**, even if configured, until reviewed per-request pricing and reservation controls exist. Use reviewed source packets or corpus inputs instead. No price was invented to preserve unbounded paid search.

## Important limitations and intentional incompatibilities

The estimate uses static prices and conservative text-token bounds. Provider price changes, premiums, unexpected billing, token-bound errors or unmodeled fees can invalidate it. The overrun latch uses the same static prices: it cannot independently discover a provider price increase. Other apps, API keys, workspaces and charge categories are outside this local ledger.

Default 8192-token output quotes can exceed existing small policy limits; for example, an Opus quote can exceed the default sota allowance. Unknown/custom model names previously accepted via fuzzy price lookup now fail closed. Missing usage leaves durable liability rather than granting free retries. Do not raise budgets or release ambiguous holds simply to make probes succeed.

The additive ledger migration 011 must be reviewed and applied through the normal workspace migration path before paid use. Missing schema fails closed. Initialization/setup may require migration before a provider probe. No migration or configuration is automatically executed by opening this PR.

A hold may be released only when dispatch is proven not to have occurred. Timeouts and old holds are not proof. Reconcile them against provider billing under an explicit review process; this patch does not supply automated reconciliation.

## Verification and remaining gates

- 68 focused tests pass: 46 independent adversarial cases plus reservation and paid-search tests. HTTP is mocked; the local verification runner denied external socket connections and stripped inherited spend credentials.
- Adversarial coverage includes attempt-visible holds, concurrent admission, stricter caller caps, workspace isolation, known-usage invalid JSON, missing/malformed usage, transport/model mismatch, replay accounting, cross-date holds, corrupted rows, overrun latching and settlement rollback.
- Broader local unit/security/contract verification: 1,073 passed, two skipped, one failed. The failure was a missing optional Playwright Chromium headless-shell executable, before browser assertions. Skips were the release-only unstaged SPA wheel and an unconfigured credential-dependent Roamboard live smoke test; the LLM live-smoke module was explicitly excluded. This is not a claim of a clean full suite.
- Modified production code passes focused Ruff; cost/provider/budget pass targeted Pyright. Independent tests are included under tests/security with formatting/import cleanup only, retaining their assertions.

Before activation: independently review integration, initialize/migrate a disposable workspace, run the browser/release gates with their prerequisites, verify current provider pricing/account caps, and exercise the intended workflows in staging. Keep deployment and any live paid smoke call separately authorized. Existing dependency remediation is a separate concern.

## 2026-10-26 snapshot reconciliation

The current provider defaults and documented request contracts were reviewed against
primary documentation and unauthenticated model metadata. No paid probe or account
credentials were used; this is documented compatibility, not a live-provider receipt.
The 30-day release-evidence expiry remains in force, and the audit now also compares
the executable admission prices and documented live aliases with the reviewed record.

- [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/) and
  [change log](https://api-docs.deepseek.com/updates/) identify `deepseek-flash` as
  the current Flash request model. New default selections use it. The documented
  `deepseek-v4-flash` redirect uses the same peak uncached $0.30/$1.20 rates per
  million input/output tokens; Pro uses $1.32/$3.96. Discontinued `deepseek-chat`
  and `deepseek-reasoner` retain historical receipt rates but deny live dispatch.
- OpenRouter's public endpoint metadata for
  [GLM 5.2](https://openrouter.ai/api/v1/models/z-ai/glm-5.2/endpoints) (34 routes)
  and [Opus 5](https://openrouter.ai/api/v1/models/anthropic/claude-opus-5/endpoints)
  (11 routes) is more conservative than the model page's advertised entry price.
  GLM admission uses the maxima $2.31/$8.00. Opus uses $20/$50, including the
  highest input cache-write and fast/regional output prices. Gateway prices are
  separate from first-party prices. Other gateway models and variants deny live
  dispatch until their route prices are reviewed.
- [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)
  and [deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations)
  still document the existing Haiku 4.5 / Opus 5 defaults. OpenAI's documented
  [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) rate is unchanged;
  the higher existing [Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
  snapshot is retained instead of reducing admission for a temporary promotion.

These rates are conservative local estimates and may reduce availability under
existing small budgets. No budgets or holds were relaxed. Account fees, other
consumers and future price changes remain outside a provider-account cap proof.
Unknown or unverified endpoint/model combinations still fail closed.
