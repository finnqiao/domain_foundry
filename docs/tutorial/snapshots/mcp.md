# MCP (Claude Desktop / Cursor) — snapshot

_Driven over real stdio MCP `tools/call`, exactly as an MCP client does._

```json
### tools/list
[
  "domain_foundry_capture",
  "domain_foundry_query",
  "domain_foundry_correct",
  "domain_foundry_review_list",
  "domain_foundry_review_resolve",
  "domain_foundry_new_domain",
  "domain_foundry_wizard_reply",
  "domain_foundry_health"
]

### new_domain
{
  "session_id": "wz_01KYA7EXY7MSVMM5MX4YCZRS2N",
  "state": "interview",
  "domain": "bouldering"
}

### wizard_reply(skip)
{
  "state": "test_drive",
  "domain": "bouldering"
}

### capture
{
  "status": "applied",
  "domain": "bouldering",
  "object_type": "entry",
  "confidence": 0.95
}

### query
{
  "rows": 1,
  "first": "good bouldering session at the gym, felt strong"
}

### correct
{
  "action": "amend",
  "applied": true,
  "eval_case": true
}

### review_list
{
  "pending": 0
}

### health
{
  "ok": true
}
```
