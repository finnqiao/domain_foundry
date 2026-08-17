import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api } from "../lib/api";
import type { BlockData, PackCard, PackView } from "../lib/types";
import { resolveBlock } from "../blocks/registry";
import { EmptyState } from "../blocks/kit";
import { useNav } from "../lib/nav";
import { Composer, consumeJustInstalled } from "./Composer";

function consumeShortlist(_domain: string): string[] {
  try {
    const raw = window.sessionStorage.getItem("df:shortlist");
    if (!raw) return [];
    const scoped = window.sessionStorage.getItem("df:shortlist-domain");
    if (scoped && scoped !== _domain) return [];
    window.sessionStorage.removeItem("df:shortlist");
    window.sessionStorage.removeItem("df:shortlist-domain");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map(String).slice(0, 8) : [];
  } catch {
    return [];
  }
}

// Renders one domain: a tab per pack view, each backed by a built-in (or
// side-loaded) block bound to /api/blocks/<view>/data.
export function DomainView({ pack }: { pack: PackCard }) {
  const { route, navigate, openDetail, refreshKey, refresh } = useNav();
  const [views, setViews] = useState<PackView[]>([]);
  const [data, setData] = useState<BlockData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [focusOnMount] = useState(() => consumeJustInstalled(pack.name));
  const [shortlist] = useState(() => consumeShortlist(pack.name));

  const activeId = route.name === "domain" ? route.viewId : undefined;

  useEffect(() => {
    api
      .blockViews(pack.name)
      .then((vs) => {
        setViews(vs);
        if (!activeId && vs.length > 0) {
          navigate({ name: "domain", domain: pack.name, viewId: vs[0].id }, { replace: true });
        }
      })
      .catch((e) => setErr(String(e)));
  }, [activeId, navigate, pack.name]);

  const activeView = useMemo(() => views.find((v) => v.id === activeId) ?? views[0], [views, activeId]);
  const activeViewId = activeView?.id;

  useEffect(() => {
    if (!activeViewId) return;
    setLoading(true);
    api
      .blockData(pack.name, activeViewId)
      .then((d) => {
        setData(d);
        setErr(null);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [activeViewId, pack.name, refreshKey]);

  const BlockComponent = activeView ? resolveBlock(activeView.block) : null;

  return (
    <div
      className="domain-view"
      style={pack.accent ? ({ "--domain-accent": pack.accent } as CSSProperties) : undefined}
    >
      <div className="domain-view-head">
        <h2>
          <span className="domain-icon" aria-hidden>{pack.icon}</span> {pack.title}
        </h2>
        {shortlist.length > 0 && (
          <div className="wizard-questions" aria-label="Fields we’ll file">
            {shortlist.map((chip) => (
              <span className="chip" key={chip}>
                {chip}
              </span>
            ))}
          </div>
        )}
      </div>

      <Composer domain={pack.name} packs={[pack]} focusOnMount={focusOnMount} onDone={() => refresh()} />
      <SuggestBanner domain={pack.name} />

      <div
        className="tabs"
        role="tablist"
        tabIndex={-1}
        aria-label={`${pack.title} views`}
        onKeyDown={(event) => {
          if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
          const index = views.findIndex((view) => view.id === activeView?.id);
          if (index < 0 || views.length === 0) return;
          const next = views[(index + (event.key === "ArrowRight" ? 1 : views.length - 1)) % views.length];
          navigate({ name: "domain", domain: pack.name, viewId: next.id });
          tabRefs.current[next.id]?.focus();
          event.preventDefault();
        }}
      >
        {views.map((v) => (
          <button
            key={v.id}
            ref={(element) => { tabRefs.current[v.id] = element; }}
            type="button"
            role="tab"
            id={`tab-${v.id}`}
            aria-selected={activeView?.id === v.id}
            aria-controls="view-panel"
            tabIndex={activeView?.id === v.id ? 0 : -1}
            className={`tab${activeView?.id === v.id ? " tab-active" : ""}`}
            onClick={() => navigate({ name: "domain", domain: pack.name, viewId: v.id })}
          >
            {v.title}
          </button>
        ))}
      </div>

      <div
        className="block-surface"
        id="view-panel"
        role="tabpanel"
        aria-labelledby={activeView ? `tab-${activeView.id}` : undefined}
      >
        {err && <p className="error">{err}</p>}
        {loading && <p className="muted">Loading…</p>}
        {!loading && data && !!data["error"] && (
          <EmptyState title="This view can’t render yet" hint={String(data["error"])} />
        )}
        {!loading && activeView && data && !data["error"] && BlockComponent && (
          <BlockComponent
            domain={pack.name}
            view={activeView}
            data={data}
            onOpenDetail={(objectType, uid) => openDetail({ domain: pack.name, objectType, uid })}
            onChanged={refresh}
          />
        )}
        {!loading && activeView && !BlockComponent && (
          <EmptyState
            title={`No renderer for “${activeView.block}”`}
            hint="This block isn’t built in. Side-load it from ~/.domain_foundry/blocks/ (see Docs)."
          />
        )}
      </div>
    </div>
  );
}

function SuggestBanner({ domain }: { domain: string }) {
  const [text, setText] = useState<string | null>(null);
  const [edit, setEdit] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { refresh } = useNav();

  useEffect(() => {
    let active = true;
    api
      .wizardSuggest(domain)
      .then((payload) => {
        if (!active) return;
        const suggestion = payload.suggestion;
        setText(suggestion?.suggestion ?? null);
        setEdit(suggestion?.apply_edit ?? null);
      })
      .catch(() => {
        if (active) setText(null);
      });
    return () => {
      active = false;
    };
  }, [domain]);

  if (!text) return null;

  async function apply() {
    if (!edit) return;
    setBusy(true);
    try {
      await api.hardeningApply(domain, edit);
      refresh();
      setText(null);
    } catch {
      setBusy(false);
    }
  }

  return (
    <aside className="suggest-banner" aria-label="Next idea">
      <p>{text}</p>
      {edit && (
        <button className="btn-secondary" type="button" disabled={busy} onClick={() => void apply()}>
          {busy ? "Adding…" : "Add this"}
        </button>
      )}
    </aside>
  );
}
