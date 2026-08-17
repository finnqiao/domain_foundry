# Pack capabilities and compatibility

Slice 3 makes experience capabilities declarative at the pack boundary. A
pack may include `capabilities.yaml` with two top-level sections:

```yaml
compatibility:
  core: ">=0.1,<2"
  capabilities:
    derived_metrics: ">=1,<2"
capabilities:
  derived_metrics:
    version: 1
```

The loader validates this metadata before registration. Capability names and
their supported major versions are defined by the core registry. A pack is
rejected when it names an unknown capability, requests a newer version, or
declares a core range that excludes the running core. This makes pack/core
compatibility a visible contract instead of an accidental import-time failure.

## Capability shapes

| Capability | Pack-owned declaration | Generic consumer | Slice 3 proof |
| --- | --- | --- | --- |
| `derived_metrics` | Safe arithmetic expressions, source fields, units, precision | Projection compiler and restricted evaluator | Sourdough hydration/bulk metrics; held-out coffee ratio/yield |
| `media` | Gallery id, object type, attachment field/source, accepted media types | Generic gallery block and content-addressed attachment route | Sourdough crumb gallery; held-out coffee brew gallery |
| `compare` | Object type, label field, metric ids | Generic comparison projection/block | Sourdough bakes; held-out coffee brews |
| `imports` | Mapping, source format, fixture, entity/field maps | Preview/commit importer with provenance and idempotency | Japanese deterministic fixture |
| `sessions` | Session kind, lifecycle, state vocabulary | Session shell and activity receipt | Japanese quiz start/resume/grade/activity |
| `schedules` | Timezone, missed-run policy, status controls | Durable schedule-status shell | Japanese pause/resume metadata and run state |

The generic consumer reads declaration data. It does not inspect the pack name
or carry a branch for a domain. Derived expressions intentionally support a
small arithmetic language over current/previous row values (`+`, `-`, `*`,
`/`, `abs`, `round`, `min`, and `max`). Missing inputs produce an unavailable
metric; they do not become fabricated evidence.

## Evidence and integration boundaries

The import preview and commit endpoints report source references, channels,
timestamps, and receipts. A fixture is a deterministic test source, not a
provider response. The Japanese session shell currently exposes the local
engine and labels provider/LLM behavior as unavailable. Schedule declarations
provide durable local status and policy metadata; they do not claim a live
calendar or notification provider.

All detail actions continue to use the existing `?detail=` route and receipt
links. Media URLs are content-addressed and retain their declared content type.

## Adding a capability

1. Add the declaration and deterministic fixture to the pack.
2. Add loader validation and a generic consumer only when the capability is a
   reusable cross-domain seam.
3. Add a pack contract test and a held-out-domain test. The test should fail if
   the core starts depending on the pack name.
4. Document live-provider, calendar, LLM, and human-evidence gates explicitly.
5. Increment the capability version when the declaration contract is changed;
   do not silently reinterpret an older version.
