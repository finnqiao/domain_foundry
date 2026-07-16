import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { CatalogEntry, PackCard } from "../lib/types";
import { useNav } from "../lib/nav";

// Home: per-domain cards from pack manifests, plus a teaching empty state and
// an "add domain" picker sourced from the bundled catalog.
export function Home({ packs, onInstalled }: { packs: PackCard[]; onInstalled: () => void }) {
  const { navigate } = useNav();
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.catalog().then(setCatalog).catch(() => setCatalog([]));
  }, [packs.length]);

  async function install(name: string) {
    setBusy(name);
    setErr(null);
    try {
      await api.activatePack(name);
      onInstalled();
      setPicking(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const available = catalog.filter((c) => !c.installed);

  if (packs.length === 0) {
    return (
      <div className="home">
        <div className="empty empty-hero">
          <p className="empty-title">No domains yet</p>
          <p className="empty-hint">
            Describe what you want to track — starters and bakes, plant care, dives, a reading log — and
            you get a schema, routing, and an app view. To get going right now, install one of the
            example domains below.
          </p>
          <CatalogGrid catalog={available} onInstall={install} busy={busy} />
          {err && <p className="error">{err}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="home">
      <div className="home-head">
        <h2>Domains</h2>
        <button className="btn-secondary" onClick={() => setPicking((p) => !p)}>
          {picking ? "Close" : "Add domain"}
        </button>
      </div>

      {picking && (
        <div className="catalog-panel">
          {available.length === 0 ? (
            <p className="muted">All example domains are installed.</p>
          ) : (
            <CatalogGrid catalog={available} onInstall={install} busy={busy} />
          )}
          {err && <p className="error">{err}</p>}
        </div>
      )}

      <div className="domain-grid">
        {packs.map((p) => (
          <button key={p.name} className="domain-card" onClick={() => navigate({ name: "domain", domain: p.name })}>
            <span className="domain-icon" aria-hidden>
              {p.icon}
            </span>
            <span className="domain-name">{p.title}</span>
            <span className="domain-desc">{p.description}</span>
            <span className="domain-meta">
              {p.object_count} {p.object_count === 1 ? "object" : "objects"} · {p.views.length} views
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function CatalogGrid({
  catalog,
  onInstall,
  busy,
}: {
  catalog: CatalogEntry[];
  onInstall: (name: string) => void;
  busy: string | null;
}) {
  return (
    <div className="catalog-grid">
      {catalog.map((c) => (
        <div className="catalog-card" key={c.name}>
          <span className="domain-icon" aria-hidden>
            {c.icon}
          </span>
          <div className="catalog-info">
            <span className="domain-name">{c.title}</span>
            <span className="domain-desc">{c.description}</span>
          </div>
          <button className="btn-primary" disabled={busy === c.name} onClick={() => onInstall(c.name)}>
            {busy === c.name ? "Installing…" : "Install"}
          </button>
        </div>
      ))}
    </div>
  );
}
