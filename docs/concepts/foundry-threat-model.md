# Foundry threat model

Status: release gate
Last reviewed: 2026-08-19

## Scope and assets

The Foundry path turns a user brief and optional artifact descriptions into a
researched proposal, a selected/remixed `FoundrySpec`, and a local owned bundle.
The protected assets are provider credentials, the user's brief and local
records, source and decision provenance, the integrity of the generated schema
and app, filesystem boundaries, and the build receipt.

The trust boundaries are explicit:

1. The browser sends user-authored data to the local authenticated API.
2. The core sends a bounded brief to the configured reasoning-model provider.
3. When enabled, the research adapter sends generated queries to Brave and
   receives untrusted result metadata and snippets.
4. Typed model output crosses into the compiler only after closed-reference
   validation.
5. The compiler writes an owned bundle and the generated app stores records in
   browser local storage until the user exports them.

## Threats and controls

| Threat | Boundary | Implemented controls | Remaining validation |
|---|---|---|---|
| Credential disclosure | user → model/search | Central credential-shape check rejects the entire brief before any provider call; the UI discloses which providers receive what | Keep patterns current; users must still avoid placing confidential non-credential data in briefs |
| Prompt injection | search/model → pipeline | Search snippets are labeled untrusted; every stage has a narrow JSON schema; source, evidence, principle, concept, fragment, entity, and workload references close against supplied identifiers | Add adversarial cases whenever a provider/model changes |
| Source poisoning or unsupported authority | web → knowledge fabric | External results are build-local `reference_only` snapshots; URL, retrieval time, allowed use, and license posture are frozen; no discovered source silently becomes an approved reusable source | Human review is required before promoting a source into the maintained registry |
| Copyright/license contamination | source → generated bundle | Registry records allowed uses; reference-only material may inform paraphrased facts/patterns but code, prose, and imagery are not copied; knowledge and SBOM audits block release | Human review for novel imported assets and source packets |
| SQL injection or invalid identifiers | spec → SQLite | Strict identifier grammar, enumerated SQL types/delete behavior, escaped literals, restricted check-expression grammar, generated parameter-ready DDL, executable-schema tests | Generated migration evolution is not yet a substitute for human review of destructive changes |
| HTML/script injection | spec/records/backup → browser | Spec JSON escapes closing tags; all record and evidence strings go through HTML escaping; generated app CSP denies network connections, objects, base changes, and forms; the preview iframe is sandboxed; a browser test restores hostile markup and proves it remains inert | Manual browser security review remains required for new renderers |
| Corrupt or foreign backup | exported file → generated app | Restore is size-bounded, bound to exact spec/version, strips unknown object keys, validates field types, required values, enums, uniqueness, check constraints, and version chains before confirmation and atomic local replacement | External review should exercise browser storage quotas and unusually large valid histories |
| Filesystem traversal or partial bundles | API/compiler → disk | Proposal IDs are ULIDs, resolved app paths must remain below the Foundry app root, non-empty destinations are never overwritten, and bundles are staged then atomically renamed | Disk-full fault injection remains an operational test |
| Resource or cost exhaustion | user → providers | HTTP/core length and list bounds, bounded research queries/results, fixed stage count, and explicit provider configuration | Provider-level budgets and cancellation should be configured by operators |
| Sensitive local records | generated app → browser/export | No telemetry or generated-app network access; records stay in origin-scoped local storage; export and restore are explicit user actions; complete history remains inspectable | Local storage and JSON backups are not encrypted; shared-device users must protect the browser profile and exported files |
| Dependency/build compromise | repository → release | Locked Python/npm dependencies, vulnerability audits, SPDX SBOM, read-only CI permissions, deterministic Foundry builds, artifact hashes, and provenance attestation | External review and trusted-publisher release setup are human launch gates |

## Security invariants

- Unknown or unresearched verticals fail closed; they are not relabeled generic
  scaffolds.
- The model cannot add a source identifier that was not supplied to it and
  cannot author the only tests used to judge its output.
- Preview and owned export are the same generated HTML bytes.
- Update and correction never overwrite the prior local version; every change
  adds a receipt and survives export/restore.
- A backup from another spec, a newer runtime, or an invalid record set is
  rejected before local state changes.
- A completed bundle contains the exact spec, executable schema, frozen
  evidence, local app, README, and a receipt hashing every owned artifact.
- Generated apps make no network connections.
- No external bind is allowed without bearer authentication.

## Standards used

The verification categories follow [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)
and the model-specific boundary follows [OWASP LLMSVS](https://owasp.org/www-project-llm-verification-standard/LLMSVS-v2.0-en.html).
Build integrity and dependency evidence use [SLSA](https://slsa.dev/spec/v1.2/),
[SPDX](https://spdx.github.io/spdx-spec/v3.0.1/), and the
[REUSE specification](https://reuse.software/spec/).

## Release evidence

Automated evidence lives in `tests/security/`, `tests/unit/test_foundry_*`,
`tests/contract/test_foundry_*`, `app/e2e/foundry-goldens.spec.ts`, and
`scripts/release_audit.sh`. External penetration review, a manual screen-reader
pass, live-provider probes, and real-user validation remain named human gates;
passing the automated audit must not be described as completing them.
