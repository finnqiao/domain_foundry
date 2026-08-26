# Aquarium Water Journal — showcase target

**TARGET ARTIFACT** — the spec is hand-authored (Phase 0 bar); the bundle beside it is compiled from that spec by the real deterministic FoundryCompiler (`foundry build`), no live LLM involved. The live pipeline's acceptance test is producing a spec of this caliber unaided.

## The interest

I keep a 75-litre planted community tank, and almost everything that goes wrong in it is something the water was telling me a week earlier — a pH that drifted when the KH ran out, nitrate creeping past 20 ppm because I skipped a water change, ammonia showing up after I over-cleaned the filter. What I actually do is test with a liquid kit, write six numbers down, change 25 percent of the water, and look up whether the next fish can live in what I measured. So the app I want is a water journal with livestock attached, not a species catalogue.

This is also the audit failure this target answers: today, "fish in my aquarium tank" snaps to a scuba species pokedex — a sightings log for reef fish someone swam past. That app cannot hold a nitrite reading, a 25 percent water change, or a heater setpoint, which is the entire job.

## Acceptance utterances

The finished pipeline's app MUST file both of these without a follow-up question:

| Utterance | What it files |
|---|---|
| `added a neon tetra, parameters 6.8 pH, 78F, new plant` | Two `inhabitant` rows against the current tank — `neon tetra` (kind `fish`, *Paracheirodon innesi*) and the new plant (kind `plant`) — plus one `water_test` observation carrying `ph 6.8` and `temperature_f 78`. Nothing routes to a dive-site or species-sighting log. |
| `water change 25%, nitrates down to 10` | One `maintenance` event with `kind: water_change` and `water_change_pct: 25`, plus one `water_test` observation carrying `nitrate_ppm 10`, both against the same tank. The cadence ring resets; the nitrate trend line drops inside its safe band. |

Both are authored as `routing` evaluation cases in the spec (`aquarium_first_capture`, `aquarium_water_change`, `authored_by: user`).

## Vocabulary bar

The compiled app has to speak the keeper's language, not a generic tracker's. These terms must be present and load-bearing:

pH · ammonia · nitrite · nitrate · KH · GH · cycling · water change · stocking · neon tetra · shrimp · planted tank · filter · heater · ppm · °F/°C

Counted in `bundle/app.html`: `cycling` 21, `nitrate` 21, `pH` 21, `tetra` 7, `water change` 22.

## Domain shape

- **tank** (owned) — volume, water type, planted, `started_at`, and a lifecycle that is the nitrogen cycle itself: `cycling → cycled → established → rescaped → retired`. A nitrite spike during `cycling` is a phase; the same spike in `established` is an emergency.
- **inhabitant** (owned) — common and scientific name, kind (fish/invertebrate/plant), quantity, source, status, and the species' own temperature/pH envelope and minimum group size, Seriously Fish style.
- **water_test** (observation) — immutable readings: pH, ammonia, nitrite, nitrate, temperature, KH, GH, plus how it was measured. Corrected beside the original, never overwritten.
- **maintenance** (event) — water change, filter clean, dosing, trim, with the percentage changed.
- **equipment** (owned) — filter, heater, light, CO2, with rating, setpoint, and last service.

Three structurally distinct concepts were authored — tank-journal (selected), stocking-book, chemistry-lab — and the remix borrows two fragments: the safe-band parameter strip from chemistry-lab and species care cards from stocking-book.

## Files

| Path | What it is |
|---|---|
| `spec.yaml` | Hand-authored FoundrySpec 1.0 — the Phase-0 bar. 5 entities, 4 relationships, 6 constraints, 3 indexes, 4 workloads, 2 state machines, 4 views, 3 flows, 8 evaluation cases, 7 derivations. |
| `bundle/app.html` | Self-contained local application compiled from the spec. |
| `bundle/schema.sql` | SQLite DDL — identities, enum and range checks, foreign keys, workload-derived indexes. Verified executable. |
| `bundle/foundry-spec.json` | The validated spec as the compiler saw it. |
| `bundle/evidence.json` | Frozen source, principle, citation, and derivation snapshot. |
| `bundle/build-receipt.json` | Artifact hashes and compiler identity. |
| `bundle/README.md` | Compiler-generated bundle readme (ownership and export notes). |

## Rebuild

```bash
.venv/bin/domain-foundry foundry validate examples/showcase/aquarium/spec.yaml
rm -rf examples/showcase/aquarium/bundle
.venv/bin/domain-foundry foundry build examples/showcase/aquarium/spec.yaml \
  --output examples/showcase/aquarium/bundle
```
