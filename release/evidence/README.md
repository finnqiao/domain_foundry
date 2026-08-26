# Local release evidence

This directory receives generated candidate logs, the candidate manifest, human
review receipts, and any private reports referenced by them. Evidence is ignored
by Git by default so a reviewer can bind a receipt to the exact clean commit
without creating a circular commit-hash dependency.

Generate machine evidence with:

```bash
scripts/candidate_gate.sh
```

From that exact clean candidate, prepare the seven pending receipts and report
shells with immutable IDs, commit, artifact hashes, counts, goldens, and provider
defaults already filled:

```bash
python scripts/review_packet.py prepare
```

Complete them without secrets or personal user data. When every report is
final, bind its content hash into the corresponding receipt and audit it:

```bash
python scripts/review_packet.py seal
python scripts/public_release_audit.py
```

`prepare` refuses dirty/stale candidates and refuses to overwrite reviewer work.
`seal` rejects missing, empty, symlinked, or out-of-directory reports. Any report
edit after sealing makes the public audit fail until the reviewer reseals it.

Publish redacted reports and receipts as signed GitHub release assets after the
tag. Never commit provider keys, private user notes, or undisclosed security
findings.
