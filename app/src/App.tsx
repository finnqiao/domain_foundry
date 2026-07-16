import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./lib/api";
import type { PackCard } from "./lib/types";
import { NavContext, type DetailTarget, type Route } from "./lib/nav";
import { loadCustomBlocks } from "./blocks/customBlocks";
import { CaptureBox } from "./components/CaptureBox";
import { Home } from "./components/Home";
import { DomainView } from "./components/DomainView";
import { HealthPanel } from "./components/HealthPanel";
import { Docs } from "./components/Docs";
import { CaptureFeed } from "./blocks/CaptureFeed";
import { ReviewQueue } from "./blocks/ReviewQueue";
import { DetailModal } from "./components/DetailModal";

export function App() {
  const [route, setRoute] = useState<Route>({ name: "home" });
  const [detail, setDetail] = useState<DetailTarget | null>(null);
  const [packs, setPacks] = useState<PackCard[]>([]);
  const [reviewPending, setReviewPending] = useState<number>(0);
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  const loadPacks = useCallback(() => {
    api.packs().then(setPacks).catch(() => setPacks([]));
    api
      .reviewStats()
      .then((s) => setReviewPending(s.pending))
      .catch(() => setReviewPending(0));
  }, []);

  useEffect(() => {
    loadPacks();
  }, [loadPacks, refreshKey]);

  useEffect(() => {
    loadCustomBlocks();
  }, []);

  const nav = useMemo(
    () => ({
      route,
      navigate: setRoute,
      openDetail: (t: DetailTarget) => setDetail(t),
      refreshKey,
      refresh,
    }),
    [route, refreshKey, refresh],
  );

  const activePack = route.name === "domain" ? packs.find((p) => p.name === route.domain) : undefined;

  return (
    <NavContext.Provider value={nav}>
      <div className="layout">
        <aside className="sidebar">
          <div className="logo">
            <span className="logo-mark">◆</span>
            <span className="logo-text">domain_expert</span>
          </div>
          <nav className="side-nav" aria-label="Primary">
            <NavItem active={route.name === "home"} onClick={() => setRoute({ name: "home" })}>
              Home
            </NavItem>
            <NavItem active={route.name === "feed"} onClick={() => setRoute({ name: "feed" })}>
              Capture feed
            </NavItem>
            <NavItem active={route.name === "review"} onClick={() => setRoute({ name: "review" })}>
              Review
              {reviewPending > 0 && <span className="nav-count">{reviewPending}</span>}
            </NavItem>
            <NavItem active={route.name === "health"} onClick={() => setRoute({ name: "health" })}>
              Health
            </NavItem>
            <NavItem active={route.name === "docs"} onClick={() => setRoute({ name: "docs" })}>
              Docs
            </NavItem>
          </nav>

          {packs.length > 0 && (
            <div className="side-domains">
              <p className="side-label">Domains</p>
              {packs.map((p) => (
                <NavItem
                  key={p.name}
                  active={route.name === "domain" && route.domain === p.name}
                  onClick={() => setRoute({ name: "domain", domain: p.name })}
                >
                  <span className="side-domain-icon" aria-hidden>
                    {p.icon}
                  </span>
                  {p.title}
                </NavItem>
              ))}
            </div>
          )}
        </aside>

        <main className="content">
          {(route.name === "home" || route.name === "feed") && (
            <div className="capture-region">
              <CaptureBox onCaptured={() => refresh()} />
            </div>
          )}

          {route.name === "home" && <Home packs={packs} onInstalled={refresh} />}
          {route.name === "feed" && (
            <section className="panel">
              <h2>Capture feed</h2>
              <CaptureFeed packs={packs} refreshKey={refreshKey} />
            </section>
          )}
          {route.name === "review" && (
            <section className="panel">
              <h2>Review queue</h2>
              <ReviewQueue packs={packs} refreshKey={refreshKey} onChanged={refresh} />
            </section>
          )}
          {route.name === "health" && (
            <section className="panel">
              <h2>Health</h2>
              <HealthPanel refreshKey={refreshKey} />
            </section>
          )}
          {route.name === "docs" && (
            <section className="panel">
              <Docs />
            </section>
          )}
          {route.name === "domain" &&
            (activePack ? (
              <DomainView pack={activePack} />
            ) : (
              <section className="panel">
                <p className="muted">Loading domain…</p>
              </section>
            ))}
        </main>
      </div>

      {detail && (
        <DetailModal
          target={detail}
          packs={packs}
          onClose={() => setDetail(null)}
          onChanged={refresh}
        />
      )}
    </NavContext.Provider>
  );
}

function NavItem({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button className={`nav-item${active ? " nav-active" : ""}`} onClick={onClick} aria-current={active}>
      {children}
    </button>
  );
}
