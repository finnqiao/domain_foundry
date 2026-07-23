# Private pack overlay

Personal packs stay **outside** the public Domain Foundry checkout. The OSS repo
ships genericized demo packs under `packs/`; anything personalized (private
japanese/health/dev variants, `x_radar`, founder-only food/travel tweaks) lives
in a private directory and is discovered at runtime.

## How discovery works

`PackRegistry` loads packs from three sources, in order (later wins on name
collision):

1. **Workspace install dir** — `~/.domain_foundry/packs/` (or `$DOMAIN_FOUNDRY_HOME/packs`)
2. **Pip entry points** — group `domain_foundry.packs` (installable pack packages)
3. **Private overlay** — directories listed in `DOMAIN_FOUNDRY_PACKS_PATH`

```bash
# Catalog of personal packs outside the OSS tree (recommended layout):
export DOMAIN_FOUNDRY_PACKS_PATH=~/HermesWorkspace/packs

# Multiple roots (os.pathsep-separated; `:` on macOS/Linux):
export DOMAIN_FOUNDRY_PACKS_PATH=~/HermesWorkspace/packs:~/private/extra-packs

# A single pack directory (one that itself contains pack.yaml) is also valid:
export DOMAIN_FOUNDRY_PACKS_PATH=~/HermesWorkspace/packs/x_radar
```

Deprecated alias: `DOMAIN_FOUNDRY_PACKS` (same semantics). Prefer
`DOMAIN_FOUNDRY_PACKS_PATH`.

Entry-point packs (for remixers who publish `domain-foundry-pack-*` wheels)
register under:

```toml
[project.entry-points."domain_foundry.packs"]
my_pack = "my_pack_pkg:pack_root"
```

where `pack_root` is a `Path` (or zero-arg callable returning one) to a directory
containing `pack.yaml`.

## What stays private

| Location | Contents |
|---|---|
| `~/HermesWorkspace/packs/` (example) | Personalized / private packs |
| `DOMAIN_FOUNDRY_HOME` DBs + vault | Live data — never committed to OSS |
| Private denylist file | Names/venues for `DOMAIN_FOUNDRY_DENYLIST` — never committed |

Clean-machine / OSS dry runs leave `DOMAIN_FOUNDRY_PACKS_PATH` unset and use only
bundled demo packs (`plants`, `sourdough`, `food`, `travel`, …).

## Leakscan backstop

`scripts/leakscan.py` fails CI if personal home paths, emails, Telegram token/id
shapes, or API-key shapes appear in tracked OSS files. See
[`LEAKSCAN_PHASE9.md`](LEAKSCAN_PHASE9.md).
