# MCP (Claude Desktop / Cursor) — snapshot

_Driven over real stdio MCP `tools/call`, exactly as an MCP client does._

```json
### tools/list
[
  "domain_foundry_capture",
  "domain_foundry_query",
  "domain_foundry_ask",
  "domain_foundry_correct",
  "domain_foundry_review_list",
  "domain_foundry_review_resolve",
  "domain_foundry_new_domain",
  "domain_foundry_wizard_reply",
  "domain_foundry_atlas_search",
  "domain_foundry_inspect_pack",
  "domain_foundry_suggest",
  "domain_foundry_apply_pack_edit",
  "domain_foundry_health",
  "domain_foundry_activate_pack",
  "domain_foundry_export"
]

### new_domain
{
  "session_id": "wz_01M02EMFHKARDE4NSBP5CRB1F0",
  "state": "fork",
  "domain": null
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

### ask
{
  "mode": "search_only",
  "has_answer": true
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
