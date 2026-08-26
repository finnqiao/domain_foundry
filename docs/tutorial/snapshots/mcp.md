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
  "session_id": "wz_01M0CBP7GRFZZDWPCF1TT3BGDJ",
  "state": "fork",
  "domain": null,
  "ideas": [
    "Set completion",
    "Collection dex",
    "Card dex",
    "Pull log"
  ]
}

### wizard_reply(looks)
{
  "state": "looks",
  "looks": [
    {
      "idea_id": "collecting.catalog.card_dex",
      "title": "Card dex",
      "hero_job": "media_dex",
      "round": 1,
      "pitch": "Each card you own, with a photo \u2014 binder pages you can search."
    }
  ],
  "html_in_payload": false
}

### wizard_reply(build it)
{
  "state": "test_drive",
  "domain": "pokemon"
}

### capture
{
  "status": "applied",
  "domain": "pokemon",
  "object_type": "card",
  "confidence": 0.97
}

### query
{
  "rows": 1,
  "first": "pulled a holographic Charizard from a 151 booster, NM"
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
  "eval_case": true,
  "fields": {
    "notes": "LP"
  }
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
