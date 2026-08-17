import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { CatalogEntry, PackCard } from "../lib/types";
import { useNav } from "../lib/nav";

export function Passions({ packs, onInstalled }: { packs: PackCard[]; onInstalled: () => void }) {
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
      try {
        window.sessionStorage.setItem("df:just-installed", name);
      } catch {
        // Session storage is an enhancement; the domain remains usable without autofocus.
      }
      onInstalled();
      setPicking(false);
      navigate({ name: "domain", domain: name });
    } catch (error) {
      setErr(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  const available = catalog.filter((entry) => !entry.installed);

  return (
    <div className="passions">
      <section className="surface-intro">
        <div>
          <h1>Your passions</h1>
          <p className="muted">Small places for the things you want to remember.</p>
        </div>
        <button className="btn-secondary" type="button" onClick={() => setPicking((open) => !open)}>
          {picking ? "Close catalog" : "Add a starter"}
        </button>
      </section>

      {picking && (
        <section className="catalog-panel" aria-label="Starter passions">
          <div className="section-head compact">
            <div>
              <h2>Starter passions</h2>
              <p className="muted">Install one to see the capture loop in action.</p>
            </div>
          </div>
          {available.length === 0 ? (
            <p className="muted">All starter passions are already installed.</p>
          ) : (
            <CatalogGrid catalog={available} onInstall={install} busy={busy} />
          )}
          {err && <p className="error" role="alert">{err}</p>}
        </section>
      )}

      <div className="domain-grid">
        <button className="domain-card create-card" type="button" onClick={() => navigate({ name: "create" })}>
          <span className="domain-icon" aria-hidden>✨</span>
          <span className="domain-name">Create your own</span>
          <span className="domain-desc">Describe a passion in your own words — get an app for it.</span>
          <span className="domain-meta">Start with a sentence</span>
        </button>
        {packs.map((pack) => (
          <button
            key={pack.name}
            className="domain-card"
            type="button"
            onClick={() => navigate({ name: "domain", domain: pack.name })}
          >
            <span className="domain-icon" aria-hidden>{pack.icon}</span>
            <span className="domain-name">
              {pack.title}
              {pack.status === "scaffold" && (
                <span
                  className="badge scaffold-badge"
                  title="Uses simple matching for now. Add a model in Settings to shape this passion further."
                >
                  starter
                </span>
              )}
            </span>
            <span className="domain-desc">{pack.description}</span>
            <span className="domain-meta">
              {pack.object_count} {pack.object_count === 1 ? "entry" : "entries"} logged
            </span>
          </button>
        ))}
      </div>

      {!picking && available.length > 0 && (
        <section className="catalog-panel catalog-panel-muted">
          <p className="muted">Looking for a quick start?</p>
          <CatalogGrid catalog={available} onInstall={install} busy={busy} />
          {err && <p className="error" role="alert">{err}</p>}
        </section>
      )}
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
      {catalog.map((entry) => (
        <div className="catalog-card" key={entry.name}>
          <span className="domain-icon" aria-hidden>{entry.icon}</span>
          <div className="catalog-info">
            <span className="domain-name">{entry.title}</span>
            <span className="domain-desc">{entry.description}</span>
          </div>
          <button className="btn-primary" type="button" disabled={busy === entry.name} onClick={() => onInstall(entry.name)}>
            {busy === entry.name ? "Installing…" : "Install"}
          </button>
        </div>
      ))}
    </div>
  );
}
