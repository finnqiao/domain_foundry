# Idea atlas

The idea atlas is Domain Foundry’s index of **what people actually do** and
**what is worth building there** — including apps that already exist in the
world, and Foundry-native ideas those apps do not give you.

It is shipped YAML under `atlas/`, not a live crawl. Core stays domain-agnostic:
the wizard *queries* the atlas. Adding soccer or freediving is a YAML drop.

## Three layers

| Layer | Question | Example |
|---|---|---|
| **Topic** | Where in the world of practice is this person? | `food` → `fermentation` → sourdough; `diving` → freediving / underwater photography |
| **App idea** | What is worth building here? | Recipe lab, nutrition tracker, dining map, SAC trend, species pokedex |
| **Jobs** | How does Foundry compile that idea into a pack? | pokedex = `catalog + event_log + media_dex + atlas` |

Jobs are the compiler alphabet. They are not a second catalog: each idea node
lists `jobs[]`. Pattern cards live on those nodes.

The `graph` **job** (record-to-record links inside a pack) is unrelated to this
atlas. Product name: **idea atlas**.

## How create works

1. You name an interest (`food`, `diving`, `I want to remember the animals`).
2. Foundry matches a **neighborhood**: breadcrumb, refine (children), expand
   (adjacent / `expands_to`), and 3–6 idea cards mixing `world` and `foundry`.
3. You pick, mix, go deeper, or say “just a simple log”. Bundled packs are
   **analogs** — they install only after a 1:1 idea pick, never on the first
   sentence.
4. `compile_jobs` turns the chosen idea’s jobs into objects, views, and
   capabilities. Then you talk / file / fix as usual.
5. Residue and corrections can walk a neighbor idea (“you’ve mentioned eight
   animals — add a species pokedex?”).

No-key mode still returns the shipped neighborhood. Experts can add a local
overlay at `~/.domain_foundry/atlas/` (same ids shadow the shipped graph) and
inspect YAML before activate.

```bash
domain-foundry atlas search "diving"
domain-foundry atlas validate
domain-foundry new-domain "food"   # first turn is the neighborhood
```

MCP tools: `domain_foundry_atlas_search`, `domain_foundry_inspect_pack`,
`domain_foundry_suggest`, `domain_foundry_apply_pack_edit`. The server never
auto-picks an idea.

Held-out coverage for food / diving / sports lives in
`examples/heldout/wizard_atlas_suite.jsonl`.
