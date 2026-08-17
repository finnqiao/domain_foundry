# domain-foundry-app

The React + Vite SPA served by `domain-foundry serve` (FastAPI mounts
`app/dist`; from a wheel, the same files are staged into the package — see
`scripts/stage_webapp.sh`).

## Commands

```bash
npm ci            # reproducible install (CI uses this)
npm run dev       # Vite dev server on :5173, proxying /api + /health to :8787
npm run build     # tsc -b && vite build → dist/
npm run e2e       # Playwright activation journey (see ../scripts/e2e_server.sh)
```

## Rollup optional-dependency recovery

On some Darwin/arm64 machines a clean tree can fail Vite builds with a missing
`@rollup/rollup-darwin-arm64` optional binary after a partial `node_modules`
copy. Recovery:

```bash
cd app
rm -rf node_modules
npm ci
npm run build
```

Do not hand-edit `package-lock.json` to force the optional dep; `npm ci` from a
clean directory is the supported path.


Policy: `npm audit` must report **0 high or critical** advisories on every
release branch. Moderates are either fixed or dispositioned here with a reason
and a revisit date — never silently accepted.

| Date | Advisory | Package | Severity | Disposition |
|---|---|---|---|---|
| 2026-08-10 | GHSA-2v37-7h3g-55p8 | nanoid < 3.3.17 (transitive, via Vite) | high | Fixed via `npm audit fix` |
| 2026-08-10 | GHSA-fxqj-rqcc-2cmp | postcss ≤ 8.5.22 (transitive, via Vite) | moderate | Fixed via `npm audit fix` |

Known chores (deliberately deferred, tracked for Slice 1+):

- Vite 7 major bump (Node floor change; no security driver today).
- MapLibre chunk split — the maplibre-gl dynamic import still lands in an
  ~800 kB chunk; split with a manualChunks rule when the Map block earns
  optimization work.
- Server-side FTS for the Search block (client-side filter over served rows
  today — see `src/blocks/Search.tsx`).
