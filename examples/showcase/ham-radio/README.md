# Shack Logbook — ham radio contacts

**TARGET ARTIFACT** — the spec is hand-authored (Phase 0 bar); the bundle beside it is compiled from that spec by the real deterministic FoundryCompiler (`foundry build`), no live LLM involved. The live pipeline's acceptance test is producing a spec of this caliber unaided.

## The interest

An amateur operator sits down at the rig, calls CQ or answers one, and trades callsigns and signal reports with a stranger — sometimes for thirty seconds, sometimes across half the planet. Every one of those contacts has to land in a log before the next caller arrives, stamped in UTC, because that log is the only proof the contact happened and the only thing that counts toward an award. What the operator wants back from it is three answers: what did I just work, which DXCC entities are worked but still waiting on a confirmation, and what time of day does this antenna actually get out.

## Acceptance utterances

The finished pipeline's app must file both of these without a second pass:

- **"worked JA1RQK on 20 meters, RST 59, QSL via bureau"** files one `qso`: `callsign` JA1RQK, `band` 20m, `mode` SSB, `rst_sent` "59", `qso_at` stamped in UTC, `station_id` pointing at the active station profile, `entity_id` resolved to the DXCC entity behind the JA prefix (Japan). It also opens one `qsl_record` on `route` bureau in state `requested` — worked, not yet confirmed.
- **"FT8 contact with VK3 on 40m, -12 both ways"** files one `qso`: `band` 40m, `mode` FT8, `rst_sent` "-12" and `rst_rcvd` "-12" held verbatim as text rather than coerced into a three-digit RST, `entity_id` resolved to Australia from the VK prefix. No QSL trail is assumed — FT8 operators usually confirm through LoTW, and the log waits for the operator to say so.

The second utterance is the honest-modeling test: a spec that types the report fields as integers cannot file it.

## Vocabulary bar

A spec at this caliber uses the operator's own words, in the operator's own sense:

| Term | What it must mean in the spec |
| --- | --- |
| QSO | One contact, the event entity, the heart of the log |
| callsign | The station worked; the first thing typed and the first thing shown |
| RST 59 | Readability-Strength-Tone report, 2–3 digits, exchanged on phone and CW |
| band | 20m / 40m / 80m — an enum, not a free-text field |
| mode | CW / SSB / FT8 / RTTY — determines what a "report" even looks like |
| QSL | The confirmation, by bureau / direct / LoTW / eQSL |
| DXCC entity | The collecting axis: 340-odd entities, each worked or confirmed |
| grid square | Maidenhead locator, for both stations — the operator's own is sensitive |
| worked / confirmed | Two different states; only confirmed counts for awards |
| rig | The transceiver on the desk, part of the station profile |
| antenna | What the signal actually left on — the other half of the profile |
| UTC | The only clock. Logs, awards, and ADIF all assume it |

## Files

| Path | What it is |
| --- | --- |
| `spec.yaml` | The hand-authored FoundrySpec — the Phase 0 bar for "ham radio contacts" |
| `bundle/app.html` | Self-contained local app compiled from the spec (93 KB, no build step) |
| `bundle/schema.sql` | SQLite DDL: 4 entities, identities, foreign keys, checks, workload indexes |
| `bundle/foundry-spec.json` | The complete normalized product and derivation contract |
| `bundle/evidence.json` | Frozen source, principle, citation, and derivation snapshot |
| `bundle/build-receipt.json` | Artifact hashes and compiler identity for the build |
| `bundle/README.md` | Compiler-generated bundle readme (how to open and own the app) |

## Reproduce

```
domain-foundry foundry validate examples/showcase/ham-radio/spec.yaml
domain-foundry foundry build   examples/showcase/ham-radio/spec.yaml --output examples/showcase/ham-radio/bundle
```

The domain is grounded in ADIF, the amateur radio interchange standard: it is why band, mode, RST, and QSL route are named fields rather than a notes blob, and why ADIF import and ADIF export both appear in `implementation` — a log that cannot speak ADIF is an island.
