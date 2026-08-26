# Independent release review guide

Status: protocol prepared; no human receipt is represented as complete.

Domain Foundry has two deliberately separate release thresholds:

1. `scripts/release_audit.sh` proves the code candidate on the current machine.
2. `scripts/public_release_audit.py` proves that independent reviewers assessed
   the exact clean commit and artifacts and that the maintainer authorized the
   irreversible publication actions.

The second command fails closed until all seven receipts exist and agree with the
candidate manifest. A green unit suite, model-written review, or unchecked box
cannot substitute for a human receipt.

## Freeze the candidate

From the clean commit proposed for `v0.1.0`:

```bash
scripts/candidate_gate.sh
```

This reruns the aggregate audit, rebuilds the SPA/wheel/sdist/SBOM, installs the
wheel in a fresh environment, compiles a shipped FoundrySpec, and writes
`release/evidence/candidate.json` plus hashed logs. The manifest binds reviews
to the commit, complete source-tree hash, three goldens, knowledge registry,
dependency-license policy and bundled notices, time-bounded naming evidence,
prototypes, wheel, sdist, and SBOM.

The browser portion does not treat a visible export control as proof. For each
golden it creates a valid domain record, downloads the generated application's
JSON export, and checks the record, spec/version identity, provenance receipt,
and derivation metadata.

Share the manifest and artifacts with reviewers. Prepare the handoff only from
the exact clean candidate:

```bash
python scripts/review_packet.py prepare
```

This creates seven pending receipts and report shells under `release/evidence/`,
pre-filling the candidate ID, commit, artifact hashes, required corpus/dependency
counts, required goldens, and expected provider defaults. Actual-review fields
remain pending, false, zero, empty, or placeholder values. The command refuses a
dirty or stale candidate and will not overwrite existing reviewer work.
Reviewers fill their own identity, observations, result, measured details, and
attestation.

After every report is final, bind its content into its receipt and run the
public audit:

```bash
python scripts/review_packet.py seal
python scripts/public_release_audit.py
```

The evidence directory is ignored so receipts can reference the exact clean
commit without creating a circular source hash. The audit requires every report
to be non-empty, contained below `release/evidence`, and equal to the SHA-256 in
its receipt; editing a sealed report invalidates the gate. Publish the redacted
reports and receipts as signed release assets.

## 1. Knowledge editorial review

Reviewer qualification: independent of the authoring work and experienced in
at least one of data architecture, product design, or software engineering. A
panel may split the disciplines, but one accountable reviewer signs the merged
receipt.

Review every source for authority, currentness, license, allowed use, and
whether the repository paraphrases rather than copies reference-only material.
Review all principles for a falsifiable rule, required evidence, failure
signals, and direct source support. Trace at least one schema, experience, and
implementation derivation in each golden back to evidence. Blocking failures
include an unsupported professional claim, unknown license, stale sole source,
or a derivation that cites no relevant evidence.

Use `knowledge_editorial.template.yaml`; its reviewed counts must cover the
candidate manifest's complete corpus.

## 2. Independent licensing review

Reviewer qualification: independent of the authoring work and experienced with
open-source licensing and redistribution obligations. This review is a release
check, not individualized legal advice.

Review the complete knowledge-source registry for license and allowed-use
posture; the cross-platform Python runtime closure; every npm dependency bundled
into the SPA; the generated-app output statement; and the candidate wheel,
sdist, SBOM, and `THIRD_PARTY_NOTICES.txt`. Confirm that:

- `release/dependency-licenses.yaml` matches the exact locked runtime versions;
- no shipped dependency has an unknown, denied, or unresolved license;
- every bundled JavaScript component's full notice is reproduced and the notice
  file is reachable in the installed application;
- reference-only research did not contribute copied code, prose, or imagery;
- generated apps do not silently relicense imported user or third-party assets.

The automated audit proves closure, exact versions, policy membership, notice
text reproducibility, and SBOM resolution. It cannot decide ambiguous ownership,
trademark, or fact-specific compatibility questions. Use
`licensing_external.template.yaml`; public release requires zero unresolved
blocking findings.

## 3. Manual accessibility review

Reviewer qualification: independent and familiar with WCAG 2.2 and at least one
desktop screen reader. Review the installed wheel, not a design file.

For the first-party Foundry flow and every compiled golden:

- complete the primary journey with keyboard only;
- complete create/correct/export with VoiceOver + Safari or NVDA + Chrome;
- verify names, roles, states, announcements, focus entry/return, and error
  recovery;
- check 200% zoom, 320 CSS-pixel reflow, high contrast, reduced motion, and
  readable evidence/schema tables;
- confirm charts or spatial views have equivalent textual data and that the
  three distinct visual systems remain operable without color or pointing.

Automated axe and reflow tests are supporting evidence, not a replacement.
Record browser, OS, screen-reader versions, journeys, failures, and retest
results in the linked report.

## 4. External security review

Reviewer qualification: independent application-security practitioner with LLM
and supply-chain familiarity. Use `docs/concepts/foundry-threat-model.md`,
`SECURITY.md`, the SBOM, and the exact candidate artifacts.

At minimum assess:

- localhost/non-local binding, bearer enforcement, CORS, Host/DNS-rebinding
  assumptions, browser-extension reach, and denial-of-service bounds;
- path traversal/symlinks, SQLite identifiers and read-only queries, migrations,
  atomic writes, archive extraction, and export injection;
- provider/search disclosure, credential rejection, prompt injection, schema
  closure, evidence-ID closure, and model-output denial of authority;
- generated HTML escaping, CSP, iframe sandbox, navigation, localStorage, and
  download behavior;
- dependencies, CI permissions, lock files, SBOM, build reproducibility, and
  release scripts.

Use OWASP ASVS and LLMVS as baselines. Public release requires no unresolved
critical or high finding; do not put undisclosed exploit details in the repo.

## 5. Live provider probes

The operator probes both current default tiers for Anthropic, OpenAI, DeepSeek,
and OpenRouter from the installed wheel. Use disposable, spend-limited keys and
never paste keys into reports:

```bash
domain-foundry setup --provider PROVIDER --non-interactive --probe
```

The receipt records the requested/resolved model, successful structured JSON,
usage metadata, UTC time, and a redacted output hash. A fallback to heuristic,
renamed model, unsupported parameter, empty JSON, or zero usage is a failure.
The current defaults and expected model IDs are already populated in the
template and bound into `candidate.json`.

Provider compatibility is a dated claim, not a permanent code fact.
`release/provider-compatibility.yaml` records the official sources used to
select every default, and `scripts/provider_compatibility_audit.py` makes the
aggregate gate fail after 30 days or whenever code and evidence drift. The
current review is based on Anthropic's
[model overview](https://platform.claude.com/docs/en/about-claude/models/overview)
and [deprecation schedule](https://platform.claude.com/docs/en/about-claude/model-deprecations),
OpenAI's pages for [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
and [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol),
DeepSeek's [change log](https://api-docs.deepseek.com/updates/) and
[current model/pricing table](https://api-docs.deepseek.com/quick_start/pricing/),
and OpenRouter's live catalog entries for
[GLM-5.2](https://openrouter.ai/z-ai/glm-5.2) and
[Claude Opus 5](https://openrouter.ai/anthropic/claude-opus-5). These sources
prove alias availability and documented request capabilities; only the live
probe proves the installed artifact works with a real account.

## 6. External-user validation

Recruit at least three people outside the authoring team with three distinct,
non-sensitive interests. Before seeing generated concepts, each participant
writes two observable tasks the app must support. Do not use the three golden
interests as the only sessions.

Observe without coaching as each participant:

1. explains their practice and constraints;
2. distinguishes the three concepts and remixes or selects one;
3. explains the proposed domain model in their own words;
4. completes the first real act and checks its provenance;
5. corrects one interpretation and exports the owned bundle.

Record completion, trust breaks, incorrect domain assumptions, time on task,
and whether the exported product matches the preview. Replace all examples with
synthetic descriptions before publishing. A critical task failure, generic
noun/color-only variation, or unexplained schema is blocking.

## 7. Name and publication authorization

Immediately before release, the maintainer rechecks PyPI names, GitHub/repository
coordinates, documentation URLs, and trademark risk; approves the public name;
and explicitly authorizes TestPyPI, PyPI, Git tag, and GitHub release actions for
the candidate hashes. This receipt is authorization, not a command for an agent
to publish. Review `release/name-availability.yaml` and rerun its source checks:
the evidence expires after seven days, PyPI 404s do not reserve names, and the
`Domain-Foundry` GitHub organization is currently occupied with unverified
ownership. The registry also records live US application `99880503` for the
exact mark and directly overlapping software services. The gate cannot pass on
a maintainer sanity check alone: the exact candidate must instead record a
rename, documented rights agreement, or named qualified legal clearance. The
approved repository in the receipt must match the candidate manifest. This
protocol records release risk; it is not legal advice.

## Final decision

Run:

```bash
python scripts/public_release_audit.py
```

It requires a clean checkout matching `candidate.json`, unchanged artifacts,
all seven receipts and their exact hashed reports, independent reviewers where
required, complete provider and golden coverage, three distinct external
participants/interests, no blocking findings, and explicit publication
authority. Only `public release audit OK` supports changing README status or
tagging the release.
