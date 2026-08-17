# CLI — snapshot

_The developer track: one command per step._

```console
$ domain-foundry init
Initialized /private~/.domain_foundry
  ledger.sqlite  schema_version=9
  domains.sqlite schema_version=1
```

```console
$ domain-foundry new-domain "track my bouldering climbing sessions" --reply skip
{
  "session_id": "wz_01M02EM92M2YHA9QEQ1PAREQJN",
  "state": "test_drive",
  "message": "Bouldering Log is ready as a simple log. Add a key in Settings to shape this interest area later. Log one real note and we'll file it. (0/2 held-out phrases matched — you can teach more later.)",
  "awaiting": "capture",
  "done": false,
… (pack generated + activated)
```

```console
$ domain-foundry capture "good bouldering session at the gym, felt strong"
Saved to Bouldering Log as an entry
```

```console
$ domain-foundry query --domain bouldering
[
  {
    "id": "01M02EMARXZMS1EZ7SMM1XGD14",
    "capture_event_id": "01M02EMARXZMS1EZ7SMM1XGD13",
    "status": "applied",
    "domain": "bouldering",
    "object_type": "entry",
    "operation": "create",
    "routing_confidence": 0.95,
    "fallback_tier": null,
    "summary": "good bouldering session at the gym, felt strong",
    "raw_text": "good bouldering session at the gym, felt strong",
    "channel": "cli",
    "created_at": "2026-08-15T10:14:10.458784Z",
    "updated_at": "2026-08-15T10:14:10.529004Z"
  }
]
```

```console
$ domain-foundry correct "actually the rating was moderate not hard"
Fixed.
```
