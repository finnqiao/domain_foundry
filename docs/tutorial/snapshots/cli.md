# CLI — snapshot

_The developer track: one command per step._

```console
$ domain-foundry init
Initialized /private~/.domain_foundry
  ledger.sqlite  schema_version=8
  domains.sqlite schema_version=1
```

```console
$ domain-foundry new-domain "track my bouldering climbing sessions" --reply skip
{
  "session_id": "wz_01KYA7EW8PHPF4E2JMRVF27H1J",
  "state": "interview",
  "message": "Here's a proposal for 'Bouldering Log' (bouldering): 1 object(s), 12 example utterances. I have 3 quick question(s) — answer any, or reply 'skip' to accept defaults.",
  "awaiting": "answers",
  "done": false,
… (pack generated + activated)
```

```console
$ domain-foundry capture "good bouldering session at the gym, felt strong"
{
  "entry_id": "01KYA7EWMJSNPFMTW46TXS12BS",
  "capture_event_id": "01KYA7EWMJSNPFMTW46TXS12BR",
  "status": "applied",
  "routed": [
    {
      "domain": "bouldering",
      "object_type": "entry",
      "operation": "create",
      "disposition": "auto_apply",
      "confidence": 0.95
    }
  ],
  "projection_status": "pending",
  "idempotent_replay": false,
  "summary": "good bouldering session at the gym, felt strong"
}
```

```console
$ domain-foundry query --domain bouldering
[
  {
    "id": "01KYA7EWMJSNPFMTW46TXS12BS",
    "capture_event_id": "01KYA7EWMJSNPFMTW46TXS12BR",
    "status": "applied",
    "domain": "bouldering",
    "object_type": "entry",
    "operation": "create",
    "routing_confidence": 0.95,
    "fallback_tier": null,
    "summary": "good bouldering session at the gym, felt strong",
    "raw_text": "good bouldering session at the gym, felt strong",
    "channel": "cli",
    "created_at": "2026-07-24T14:11:23.921986Z",
    "updated_at": "2026-07-24T14:11:23.939111Z"
  }
]
```

```console
$ domain-foundry correct "actually that bouldering session felt moderate, not hard"
{
  "action": "amend",
  "entry_id": "01KYA7EWMJSNPFMTW46TXS12BS",
  "object_uid": "bouldering:entry:01KYA7EWN09828JV15D2VEW25T",
  "correction_event_id": 1,
  "change_request_id": 2,
  "revision": null,
  "eval_case_id": "ec_01KYA7EX8XR3J7MCNJ95MJ07DS",
  "applied": true,
  "projection_status": "pending",
  "details": {
    "fields": {}
  },
  "error": null
}
```
