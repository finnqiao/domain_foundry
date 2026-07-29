# hermes-agent — snapshot

_The adapter's real tool surface (`build_tools` over the in-process client)._

```json
### domain_foundry_new_domain({'goal_text': 'track my bouldering climbing sessions'})
{
  "session_id": "wz_01KYA7EYDN900RWR5T0ZFC6G7G",
  "state": "interview",
  "message": "Here's a proposal for 'Bouldering Log' (bouldering): 1 object(s), 12 example utterances. I have 3 quick question(s) \u2014 answer any, or reply 'skip' to accept defaults.",
  "awaiting": "answers",
  "done": false,
  "domain": "bouldering",
  "proposal": {
    "domain": "bouldering",
    "title": "Bouldering Log",
    "description": "Track your bouldering over time.",
    "interpretation": "simple",
    "objects": [
      {
        "name": "entry",
        "title_field": "title",
        "fields": [
      

### domain_foundry_wizard_reply({'session_id': 'wz_01KYA7EYDN900RWR5T0ZFC6G7G', 'text': 'skip'})
{
  "session_id": "wz_01KYA7EYDN900RWR5T0ZFC6G7G",
  "state": "test_drive",
  "message": "'bouldering' is live (v0.1.0). Dry-run routed 12/12 examples (100%). Send me 5 sample messages to test-drive it \u2014 I'll explain each routing decision. You can also describe a schema edit anytime.",
  "awaiting": "capture",
  "done": false,
  "domain": "bouldering",
  "pack": {
    "name": "bouldering",
    "version": "0.1.0",
    "path": "/private/var/folders/vw/xqh73ydn483_8hc9m9t8jtdc0000gn/T/df_hermes_v2jk8jvl/packs/bouldering"
  },
  "dry_run": {
    "total": 12,
    "routed": 12,
    "accuracy": 

### domain_foundry_capture({'text': 'good bouldering session at the gym, felt strong'})
{
  "entry_id": "01KYA7EYG4W951V1PBNDNP8FED",
  "capture_event_id": "01KYA7EYG4W951V1PBNDNP8FEC",
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

### domain_foundry_query({'domain': 'bouldering'})
{
  "rows": [
    {
      "id": "01KYA7EYG4W951V1PBNDNP8FED",
      "capture_event_id": "01KYA7EYG4W951V1PBNDNP8FEC",
      "status": "applied",
      "domain": "bouldering",
      "object_type": "entry",
      "operation": "create",
      "routing_confidence": 0.95,
      "fallback_tier": null,
      "summary": "good bouldering session at the gym, felt strong",
      "raw_text": "good bouldering session at the gym, felt strong",
      "channel": "hermes-agent",
      "created_at": "2026-07-24T14:11:25.828097Z",
      "updated_at": "2026-07-24T14:11:25.844661Z"
    }
  ]
}

### domain_foundry_correct({'text': 'actually that bouldering session felt moderate, not hard'})
{
  "action": "amend",
  "entry_id": "01KYA7EYG4W951V1PBNDNP8FED",
  "object_uid": "bouldering:entry:01KYA7EYGJ6Q0G9GD5M057EPWA",
  "correction_event_id": 1,
  "change_request_id": 2,
  "revision": null,
  "eval_case_id": "ec_01KYA7EYH0WTEG4G77BBBXWTFC",
  "applied": true,
  "projection_status": "pending",
  "details": {
    "fields": {}
  },
  "error": null
}

### domain_foundry_review_list({})
{
  "items": []
}
```
