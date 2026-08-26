# hermes-agent — snapshot

_The adapter's real tool surface (`build_tools` over the in-process client)._

```json
### domain_foundry_new_domain({'goal_text': 'i collect pokemon cards'})
{
  "session_id": "wz_01M0CBP8G2WSDVVK5HT7C4HRH6",
  "state": "fork",
  "message": "You said \u201ci collect pokemon cards\u201d. You could:\n1. Set completion: How close a set is, and which rares are still missing.\n2. Collection dex: Identity, acquired-on, and a photo \u2014 a pokedex for objects.\n3. Card dex (suggested): Each card you own, with a photo \u2014 binder pages you can search.\n   a catalog you can page through \u00b7 a gallery of the photos\n4. Pull log: What came out of a pack, what you traded, and the condition.\nWhich of these, or say what you want it to do \u2014 a chart, p

### domain_foundry_wizard_reply({'session_id': 'wz_01M0CBP8G2WSDVVK5HT7C4HRH6', 'text': 'a dex of the cards i own with photos'})
{
  "session_id": "wz_01M0CBP8G2WSDVVK5HT7C4HRH6",
  "state": "looks",
  "message": "Here is a look. Pick one, tell me how to change it (darker, denser, more chart), or say 'build it'.\n1. Card dex (selected) \u2014 media_dex look (round 1)",
  "awaiting": "look",
  "done": false,
  "domain": null,
  "design_mode": "scaffold",
  "designer_model": null,
  "status": "scaffold",
  "looks": [
    {
      "idea_id": "collecting.catalog.card_dex",
      "title": "Card dex",
      "hero_job": "media_dex",
      "round": 1,
      "pitch": "Each card you own, with a photo \u2014 binder pages you can se

### domain_foundry_wizard_reply({'session_id': 'wz_01M0CBP8G2WSDVVK5HT7C4HRH6', 'text': 'build it'})
{
  "session_id": "wz_01M0CBP8G2WSDVVK5HT7C4HRH6",
  "state": "test_drive",
  "message": "Card dex is ready to try \u2014 we'll file card name \u00b7 noted at \u00b7 photos \u00b7 notes. Log one real note and we'll file it.",
  "awaiting": "capture",
  "done": false,
  "domain": "pokemon",
  "design_mode": "atlas",
  "designer_model": null,
  "status": "scaffold",
  "pack": {
    "name": "pokemon",
    "version": "0.1.0",
    "title": "Card dex",
    "path": "/private/var/folders/vw/xqh73ydn483_8hc9m9t8jtdc0000gn/T/df_hermes_uukc64ik/packs/pokemon"
  },
  "dry_run": {
    "total": 10,
    "rou

### domain_foundry_capture({'text': 'pulled a holographic Charizard from a 151 booster, NM'})
{
  "entry_id": "01M0CBP8SR4MQJC5B5P0T24H6Z",
  "capture_event_id": "01M0CBP8SR4MQJC5B5P0T24H6Y",
  "status": "applied",
  "routed": [
    {
      "domain": "pokemon",
      "object_type": "card",
      "operation": "create",
      "disposition": "auto_apply",
      "confidence": 0.97
    }
  ],
  "projection_status": "pending",
  "idempotent_replay": false,
  "summary": "pulled a holographic Charizard from a 151 booster, NM",
  "llm_error": null,
  "domain_hint": null
}

### domain_foundry_query({'domain': 'pokemon'})
{
  "rows": [
    {
      "id": "01M0CBP8SR4MQJC5B5P0T24H6Z",
      "capture_event_id": "01M0CBP8SR4MQJC5B5P0T24H6Y",
      "status": "applied",
      "domain": "pokemon",
      "object_type": "card",
      "operation": "create",
      "routing_confidence": 0.97,
      "fallback_tier": null,
      "summary": "pulled a holographic Charizard from a 151 booster, NM",
      "raw_text": "pulled a holographic Charizard from a 151 booster, NM",
      "channel": "hermes-agent",
      "created_at": "2026-08-19T06:35:12.567671Z",
      "updated_at": "2026-08-19T06:35:12.586427Z"
    }
  ]
}

### domain_foundry_ask({'question': 'what did I log?', 'domain': 'pokemon'})
{
  "question": "what did I log?",
  "answer": "I don't have that in your captured data yet.",
  "citations": [],
  "mode": "search_only",
  "plan": {
    "intent": "list",
    "domain": "pokemon",
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

### domain_foundry_correct({'text': 'that Charizard was LP not NM'})
{
  "action": "amend",
  "entry_id": "01M0CBP8SR4MQJC5B5P0T24H6Z",
  "object_uid": "pokemon:card:01M0CBP8T7Q97FKBKRQQ2X6G5D",
  "correction_event_id": 1,
  "change_request_id": 2,
  "revision": 2,
  "eval_case_id": "ec_01M0CBP8VDE4NTKND1E7NRSBNZ",
  "applied": true,
  "projection_status": "pending",
  "details": {
    "fields": {
      "notes": "LP"
    }
  },
  "error": null
}

### domain_foundry_review_list({})
{
  "items": []
}
```
