# hermes-agent — snapshot

_The adapter's real tool surface (`build_tools` over the in-process client)._

```json
### domain_foundry_new_domain({'goal_text': 'track my bouldering climbing sessions'})
{
  "session_id": "wz_01M02EMHNTA2WX10X4KSM05Q8X",
  "state": "fork",
  "message": "Sports \u2192 Climbing. Ideas: Session log, Project board\u2026 Pick an idea, refine, or say skip.",
  "awaiting": "fork",
  "done": false,
  "domain": null,
  "design_mode": null,
  "designer_model": null,
  "status": null
}

### domain_foundry_wizard_reply({'session_id': 'wz_01M02EMHNTA2WX10X4KSM05Q8X', 'text': 'skip'})
{
  "session_id": "wz_01M02EMHNTA2WX10X4KSM05Q8X",
  "state": "test_drive",
  "message": "Bouldering Log is ready as a simple log. Add a key in Settings to shape this interest area later. Log one real note and we'll file it. (0/2 held-out phrases matched \u2014 you can teach more later.)",
  "awaiting": "capture",
  "done": false,
  "domain": "bouldering",
  "design_mode": "scaffold",
  "designer_model": null,
  "status": "scaffold",
  "pack": {
    "name": "bouldering",
    "version": "0.1.0",
    "title": "Bouldering Log",
    "path": "/private/var/folders/vw/xqh73ydn483_8hc9m9t8jtdc0000gn/T

### domain_foundry_capture({'text': 'good bouldering session at the gym, felt strong'})
{
  "entry_id": "01M02EMJ0RGBA12SHX98CCX9FC",
  "capture_event_id": "01M02EMJ0RGBA12SHX98CCX9FB",
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
  "summary": "good bouldering session at the gym, felt strong",
  "llm_error": null,
  "domain_hint": null
}

### domain_foundry_query({'domain': 'bouldering'})
{
  "rows": [
    {
      "id": "01M02EMJ0RGBA12SHX98CCX9FC",
      "capture_event_id": "01M02EMJ0RGBA12SHX98CCX9FB",
      "status": "applied",
      "domain": "bouldering",
      "object_type": "entry",
      "operation": "create",
      "routing_confidence": 0.95,
      "fallback_tier": null,
      "summary": "good bouldering session at the gym, felt strong",
      "raw_text": "good bouldering session at the gym, felt strong",
      "channel": "hermes-agent",
      "created_at": "2026-08-15T10:14:17.879549Z",
      "updated_at": "2026-08-15T10:14:17.931267Z"
    }
  ]
}

### domain_foundry_ask({'question': 'what did I log?', 'domain': 'bouldering'})
{
  "question": "what did I log?",
  "answer": "I don't have that in your captured data yet.",
  "citations": [],
  "mode": "search_only",
  "plan": {
    "intent": "list",
    "domain": "bouldering",
    "object_type": null,
    "text_query": "log",
    "time_range": null,
    "aggregate": null,
    "limit": 20
  },
  "model": null,
  "cost_usd": 0.0,
  "spend_today_usd": 0.0,
  "daily_cap_usd": 0.25,
  "cap_hit": false
}

### domain_foundry_correct({'text': 'actually the rating was moderate not hard'})
{
  "action": "amend",
  "entry_id": "01M02EMJ0RGBA12SHX98CCX9FC",
  "object_uid": "bouldering:entry:01M02EMJ254HR8584YNC1E0MSC",
  "correction_event_id": 1,
  "change_request_id": 2,
  "revision": 2,
  "eval_case_id": "ec_01M02EMJ5BC7X6Y5J2BSST1WV4",
  "applied": true,
  "projection_status": "pending",
  "details": {
    "fields": {
      "rating": "moderate"
    }
  },
  "error": null
}

### domain_foundry_review_list({})
{
  "items": []
}
```
