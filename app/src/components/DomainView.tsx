import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { BlockData, PackCard, PackView } from "../lib/types";
import { resolveBlock } from "../blocks/registry";
import { EmptyState } from "../blocks/kit";
import { useNav } from "../lib/nav";

// Renders one domain: a tab per pack view, each backed by a built-in (or
// side-loaded) block bound to /api/blocks/<view>/data.
export function DomainView({ pack }: { pack: PackCard }) {
  const { route, navigate, openDetail, refreshKey, refresh } = useNav();
  const [views, setViews] = useState<PackView[]>([]);
  const [data, setData] = useState<BlockData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const activeId = route.name === "domain" ? route.viewId : undefined;

  useEffect(() => {
    api
      .blockViews(pack.name)
      .then((vs) => {
        setViews(vs);
        if (!activeId && vs.length > 0) navigate({ name: "domain", domain: pack.name, viewId: vs[0].id });
      })
      .catch((e) => setErr(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pack.name]);

  const activeView = useMemo(() => views.find((v) => v.id === activeId) ?? views[0], [views, activeId]);

  useEffect(() => {
    if (!activeView) return;
    setLoading(true);
    api
      .blockData(pack.name, activeView.id)
      .then((d) => {
        setData(d);
        setErr(null);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pack.name, activeView?.id, refreshKey]);

  const BlockComponent = activeView ? resolveBlock(activeView.block) : null;

  return (
    <div className="domain-view">
      <div className="domain-view-head">
        <h2>
          <span aria-hidden>{pack.icon}</span> {pack.title}
        </h2>
      </div>

      <nav className="tabs" role="tablist" aria-label={`${pack.title} views`}>
        {views.map((v) => (
          <button
            key={v.id}
            role="tab"
            aria-selected={activeView?.id === v.id}
            className={`tab${activeView?.id === v.id ? " tab-active" : ""}`}
            onClick={() => navigate({ name: "domain", domain: pack.name, viewId: v.id })}
          >
            {v.title}
          </button>
        ))}
      </nav>

      <div className="block-surface">
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
