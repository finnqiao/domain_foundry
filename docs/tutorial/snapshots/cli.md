# CLI — snapshot

_The developer track: one command per step._

```console
$ domain-foundry init
Initialized ~/.domain_foundry
  ledger.sqlite  schema_version=9
  domains.sqlite schema_version=1
```

```console
$ domain-foundry new-domain "i collect pokemon cards"
{
  "session_id": "wz_01M0CBP4P36J9NM6QMVB3Z09H0",
  "state": "fork",
  "message": "You said “i collect pokemon cards”. You could:\n1. Set completion: How close a set is, and which rares are still missing.\n2. Collection dex: Identity, acquired-on, and a photo — a pokedex for objects.\n3. Card dex (suggested): Each card you own, with a photo — binder pages you can search.\n   a catalog you can page through · a gallery of the photos\n4. Pull log: What came out of a pack, what you traded, and the condition.\nWhich of these, or say what you want it to do — a chart, photos, a mix board. Paste a notes folder path to ingest text. Photos: have your agent read them first, then send the text.",
  "awaiting": "fork",
  "done": false,
  "domain": null,
  "design_mode": "scaffold",
…
```

```console
$ domain-foundry wizard reply wz_01M0CBP4P36J9NM6QMVB3Z09H0 "a dex of the cards i own with photos"
{
  "session_id": "wz_01M0CBP4P36J9NM6QMVB3Z09H0",
  "state": "looks",
  "message": "Here is a look. Pick one, tell me how to change it (darker, denser, more chart), or say 'build it'.\n1. Card dex (selected) — media_dex look (round 1)",
  "awaiting": "look",
  "done": false,
  "domain": null,
  "design_mode": "scaffold",
…
```

```console
$ domain-foundry wizard reply wz_01M0CBP4P36J9NM6QMVB3Z09H0 "build it"
{
  "session_id": "wz_01M0CBP4P36J9NM6QMVB3Z09H0",
  "state": "test_drive",
  "message": "Card dex is ready to try — we'll file card name · noted at · photos · notes. Log one real note and we'll file it.",
  "awaiting": "capture",
  "done": false,
  "domain": "pokemon",
  "design_mode": "atlas",
…
```

```console
$ domain-foundry capture "pulled a holographic Charizard from a 151 booster, NM"
Saved to Card dex as a card
```

```console
$ domain-foundry query --domain pokemon
[
  {
    "id": "01M0CBP61JP5CJH3XY9WFDJ07F",
    "capture_event_id": "01M0CBP61JP5CJH3XY9WFDJ07E",
    "status": "applied",
    "domain": "pokemon",
    "object_type": "card",
    "operation": "create",
    "routing_confidence": 0.97,
    "fallback_tier": null,
    "summary": "pulled a holographic Charizard from a 151 booster, NM",
    "raw_text": "pulled a holographic Charizard from a 151 booster, NM",
    "channel": "cli",
    "created_at": "2026-08-19T06:35:09.745347Z",
    "updated_at": "2026-08-19T06:35:09.766831Z"
  }
]
```

```console
$ domain-foundry correct "that Charizard was LP not NM"
Fixed.
```
