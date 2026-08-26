# Slice 4 security review record

Status: automated/local review complete; independent external review remains a
release gate.

This record is the evidence boundary for the ecosystem preview. It describes
what the repository proves today and does not turn planned human review into a
claim.

## Automated coverage

| Surface | Control | Evidence |
|---|---|---|
| Local HTTP | bearer token on every route when configured; non-local binds require a token; CORS is allowlisted | `tests/security/test_api_auth.py` |
| Pack paths | pack roots and descendants reject symlinks; traversal and unsafe vault paths are rejected | `tests/security/test_path_and_sql.py`, pack loader validation |
| Pack content | executable-looking files, oversized files, unknown capabilities, unsupported permissions, and incompatible core ranges are rejected | `core/domain_foundry_core/packs/loader.py`, pack tests |
| SQL | identifiers are compiled from validated pack names/fields; read paths use the read-only allowlist; migrations reject destructive verbs | `tests/security/test_path_and_sql.py`, `tests/contract/test_pack_conformance.py` |
| Lifecycle | permissions are previewed before install; upgrades snapshot; rollback is backup-scoped; uninstall removes workspace-owned tables and matching projection queue state | `tests/contract/test_pack_lifecycle.py` |
| Captured text / Ask | captured content is data, not instructions; Ask plans are schema-validated and query-only; destructive operations remain policy-gated | Ask contract/security tests and `docs/security.md` |
| Pack-author proof | deep validation, positive/negative routing, fixtures, lifecycle, and orphan-table checks run from one deterministic JSON command | `scripts/pack_conformance.py` |

The conformance command is local and runs its lifecycle proof in a temporary
workspace. It does not upload a pack, execute pack code, or contact a provider.

```bash
python scripts/pack_conformance.py examples/heldout/packs/coffee
```

## Explicitly pending human review

The following are not represented as completed by this repository:

- independent review of DNS rebinding, Host-header handling, browser-extension
  reach, and a live non-local deployment;
- review of custom browser blocks and separately installed behavior adapters;
- adversarial prompt-injection review by an external security reviewer;
- three external pack authors, three external users, and their friction reports;
- publication, signing, or operation of any open pack registry.

Before a technical-preview label is changed, an external reviewer must record
findings and disposition them here or in a linked issue. The human evidence
must include the exact build under review and must not be replaced by fixture
counts.

The current exact-artifact scope, report requirements, and receipt format are
in [`release-review-guide.md`](release-review-guide.md). A completed external
review must make the `security_external` row of
`scripts/public_release_audit.py` pass; this record alone is not a receipt.

## Compatibility and deprecation policy

Pack manifests declare a core compatibility range and capabilities are
versioned independently. A pack requesting an unsupported capability or
incompatible core is rejected before installation. Declarative packs cannot
request network access, arbitrary code execution, or ambient credentials.

The `domain-foundry-pack-conformance/1` JSON report and the lifecycle HTTP/CLI
receipts are preview contracts. Breaking either requires a new report/API
version, a migration note, and a deprecation window in the release notes.
There is no implicit remote registry or automatic pack update path.
