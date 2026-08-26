import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./lib/api";
import type { PackCard } from "./lib/types";
import { NavContext, type DetailTarget, type Route } from "./lib/nav";
import { fromLocation, toLocation } from "./lib/router";
import { loadCustomBlocks } from "./blocks/customBlocks";
import { DomainView } from "./components/DomainView";
import { DetailModal } from "./components/DetailModal";
import { Today } from "./components/Today";
import { Passions } from "./components/Passions";
import { Inbox } from "./components/Inbox";
import { Settings } from "./components/Settings";
import { CreateDomain } from "./components/CreateDomain";
import { FoundryStudio } from "./components/FoundryStudio";

export function App() {
  const [{ route, detail }, setLocation] = useState(() =>
    fromLocation(window.location.pathname, window.location.search),
  );
  const [packs, setPacks] = useState<PackCard[]>([]);
  const [reviewPending, setReviewPending] = useState(0);
  const [unfiledCount, setUnfiledCount] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(() => setRefreshKey((key) => key + 1), []);

  const loadPacks = useCallback(() => {
    api.packs().then(setPacks).catch(() => setPacks([]));
    api.reviewStats().then((stats) => setReviewPending(stats.pending)).catch(() => setReviewPending(0));
    api.query({ status: "unfiled", limit: 100 }).then((rows) => setUnfiledCount(rows.length)).catch(() => setUnfiledCount(0));
  }, []);

  useEffect(() => {
    loadPacks();
  }, [loadPacks, refreshKey]);

  useEffect(() => {
    loadCustomBlocks();
  }, []);

  const navigate = useCallback((next: Route, options?: { replace?: boolean }) => {
    setLocation(() => {
      const location = toLocation(next, null);
      const current = window.location.pathname + window.location.search;
      if (location !== current) {
        if (options?.replace) window.history.replaceState(null, "", location);
        else window.history.pushState(null, "", location);
      }
      return { route: next, detail: null };
    });
  }, []);

  const openDetail = useCallback((target: DetailTarget) => {
    setLocation((current) => {
      const location = toLocation(current.route, target);
      window.history.pushState(null, "", location);
      return { ...current, detail: target };
    });
  }, []);

  const closeDetail = useCallback(() => {
    setLocation((current) => {
      const location = toLocation(current.route, null);
      window.history.pushState(null, "", location);
      return { ...current, detail: null };
    });
  }, []);

  useEffect(() => {
    const onPopState = () => setLocation(fromLocation(window.location.pathname, window.location.search));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const nav = useMemo(
    () => ({ route, navigate, openDetail, closeDetail, refreshKey, refresh }),
    [route, navigate, openDetail, closeDetail, refreshKey, refresh],
  );

  const activePack = route.name === "domain" ? packs.find((pack) => pack.name === route.domain) : undefined;
  const attentionCount = reviewPending + unfiledCount;

  return (
    <NavContext.Provider value={nav}>
      <a className="skip-link" href="#main">Skip to content</a>
      <div className="layout">
        <aside className="sidebar">
          <div className="logo">
            <span className="logo-mark" aria-hidden>◆</span>
            <span className="logo-text">Domain Foundry</span>
          </div>
          <nav className="side-nav" aria-label="Primary">
            <NavItem active={route.name === "foundry"} onClick={() => navigate({ name: "foundry" })}>
              Foundry
            </NavItem>
            <NavItem active={route.name === "today"} onClick={() => navigate({ name: "today" })}>
              Today
            </NavItem>
            <NavItem active={route.name === "passions"} onClick={() => navigate({ name: "passions" })}>
              Your passions
            </NavItem>
            <NavItem active={route.name === "inbox"} onClick={() => navigate({ name: "inbox" })}>
              Inbox
              {attentionCount > 0 && <span className="nav-count">{attentionCount > 99 ? "99+" : attentionCount}</span>}
            </NavItem>
            <NavItem active={route.name === "settings"} onClick={() => navigate({ name: "settings" })}>
              Settings
            </NavItem>
          </nav>

          {packs.length > 0 && (
            <div className="side-domains">
              <p className="side-label">Your passions</p>
              {packs.map((pack) => (
                <NavItem
                  key={pack.name}
                  active={route.name === "domain" && route.domain === pack.name}
                  onClick={() => navigate({ name: "domain", domain: pack.name })}
                >
                  <span className="side-domain-icon" aria-hidden>{pack.icon}</span>
                  {pack.title}
                </NavItem>
              ))}
            </div>
          )}
        </aside>

        <main className={`content${route.name === "foundry" ? " foundry-content" : ""}`} id="main" tabIndex={-1}>
          {route.name === "today" && <Today packs={packs} />}
          {route.name === "passions" && <Passions packs={packs} onInstalled={refresh} />}
          {route.name === "inbox" && <Inbox packs={packs} refreshKey={refreshKey} onChanged={refresh} />}
          {route.name === "create" && <CreateDomain onDone={refresh} />}
          {route.name === "foundry" && <FoundryStudio />}
          {route.name === "settings" && <Settings tab={route.tab} packs={packs} refreshKey={refreshKey} />}
          {route.name === "domain" &&
            (activePack ? (
              <DomainView pack={activePack} />
            ) : (
              <section className="panel"><p className="muted">Loading passion…</p></section>
            ))}
        </main>
      </div>

      {detail && (
        <DetailModal target={detail} packs={packs} onClose={closeDetail} onChanged={refresh} onOpenDetail={openDetail} />
      )}
    </NavContext.Provider>
  );
}

function NavItem({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      className={`nav-item${active ? " nav-active" : ""}`}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
    >
      {children}
    </button>
  );
}
