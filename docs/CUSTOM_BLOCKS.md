# Custom blocks & the app-shell remix path

The universal app shell (P5) renders every domain from **blocks** — reusable
view components bound to data the core API serves. There are three levels of
remix, in increasing order of power (plan §9.3).

## 1. Config-level remix (most users — no code)

Rearrange views, choose blocks, and tune facets/measures in a pack's
`projections.yaml`. Because block data is compiled from the schema, adding a
field to `schema.yaml` automatically makes it available to columns, facets, and
measures.

```yaml
app:
  icon: "🍞"
  views:
    - {id: bakes,  title: "Bakes",   block: timeline, object: bake, config: {date_field: baked_at}}
    - {id: find,   title: "Find",    block: search,   objects: [bake], config: {facets: [flour_mix, result]}}
    - {id: stats,  title: "Progress",block: stats,    object: bake, config: {measures: [{field: result, agg: distribution}]}}
```

### Built-in blocks (v1)

| Block | Scope | Data contract |
|---|---|---|
| `capture_feed` | global surface | entries |
| `list` | per-domain view | `object`, optional `columns`, `group_by` |
| `timeline` | per-domain view | `object`, `date_field` |
| `detail` | global overlay | `object_uid` |
| `search` | per-domain view | `objects`, optional `facets` |
| `stats` | per-domain view | `object`, `measures` (field × agg) |
| `history` | per-domain view | `object`, `period` (day/week/month) |
| `planner` | per-domain view | `object`, `date_field` |
| `review_queue` | global surface | approvals |

## 2. Custom block (React devs)

A custom block is a React component that receives `BlockProps`
(`domain`, `view`, `data`, `onOpenDetail`, `onChanged`) and renders data served
by `/api/blocks/<view_id>/data`. Blocks never query SQL — the core compiles the
pack's binding into a safe, read-only parameterized query.

You can ship a block two ways:

### In-tree (via PR)

Add the component and register it in `app/src/blocks/registry.ts`:

```ts
import { registerBlock } from "./registry";
import { Gauge } from "./Gauge";
registerBlock("gauge", Gauge);
```

### Side-loaded (dev path — no rebuild of the shell)

1. Build an ESM bundle that exports a `register(registerBlock)` function
   (use the app's Vite config so React is externalized):

   ```js
   // index.js
   export function register(registerBlock) {
     registerBlock("gauge", GaugeBlock);
     return ["gauge"]; // ids you registered
   }
   ```

2. Drop the bundle at `~/.domain_expert/blocks/index.js`. `domain-expert serve`
   exposes the `blocks/` directory read-only at `/custom-blocks/`, and the shell
   imports `/custom-blocks/index.js` at startup (silently ignored if absent).

3. Reference the block from any pack view:

   ```yaml
   - {id: gauge, title: "Gauge", block: gauge, object: bake, config: {field: hydration}}
   ```

> **Trust model (plan §12.4):** side-loaded blocks are **trusted code** — they
> run in your browser session with full app access. Only load bundles you wrote
> or audited. Packs (YAML) can never execute code; custom blocks can.

## 3. Bespoke app (power users)

Everything the shell does is over the same HTTP API. Point any external app at
the read paths (`/api/blocks/*`, `/api/query`, `/api/objects/*`,
`/api/packs`, `/api/health`) and mutate only through `/api/capture` and
`/api/correct`. The shell has **no privileged write path**; neither should
yours.
