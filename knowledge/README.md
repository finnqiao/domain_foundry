# Domain Foundry knowledge fabric

This directory is the structured, cited evidence substrate used to design a
domain, schema, experience, and implementation. It is deliberately separate
from the idea atlas: an atlas entry is a discovery hint; knowledge here must
identify its source, allowed use, review state, and the decisions it supports.

`status: approved` means a source passed the repository's authority, license,
freshness, and allowed-use checks and is eligible for compilation. It does not
claim independent human endorsement. The initial corpus is an agent-assisted
research synthesis; an independent editorial pass remains a public-release
gate and is recorded at the registry root.

## Rules

1. A generated decision must cite a principle or a user decision.
2. A principle must cite at least one approved or reference-only source.
3. Discovery lists are never authoritative evidence by themselves.
4. Source code or visual assets may only be copied when `allowed_uses`
   explicitly permits it. `reference_only` means facts and patterns may be
   paraphrased with attribution; no code, prose, or imagery is copied.
5. Stale, deprecated, or license-unknown sources cannot independently justify
   a release-blocking decision.
6. Domain-specific evidence lives beside the golden specification that uses it,
   while reusable professional guidance lives under `principles/`.

Run the corpus audit from the repository root:

```bash
python scripts/knowledge_audit.py
```

Future connectors may propose candidate evidence, but only an explicit
repository review can change a source or principle to `approved`.
