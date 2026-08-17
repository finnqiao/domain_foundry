import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { BlockProps } from "./kit";
import { EmptyState, ObjectCard, rowsOf } from "./kit";
import { fmtFieldName, fmtValue } from "../lib/format";
import type { Row } from "../lib/types";

const BASE = new Set(["id", "object_uid", "entry_id", "tombstoned", "created_at", "updated_at", "object_type"]);

// Facets stay local to the rows in this view; free-text search asks the server's
// FTS endpoint first and falls back to the old local filter if unavailable.
export function Search({ data, domain, onOpenDetail }: BlockProps) {
  const rows = rowsOf(data);
  const objectType = data["object_type"] as string | undefined;
  const [q, setQ] = useState("");
  const [facet, setFacet] = useState<{ field: string; value: string } | null>(null);
  const [serverMatches, setServerMatches] = useState<Set<string> | null>(null);

  const facets = useMemo(() => deriveFacets(rows), [rows]);

  useEffect(() => {
    if (q.trim().length < 2) {
      setServerMatches(null);
      return;
    }
    const timer = window.setTimeout(() => {
      void api
        .searchLedger(q, { domain, objectType, kind: "canonical" })
        .then((result) => setServerMatches(new Set(result.hits.map((hit) => hit.ref_id))))
        .catch(() => setServerMatches(null));
    }, 200);
    return () => window.clearTimeout(timer);
  }, [domain, objectType, q]);

  const filtered = rows.filter((row) => {
    if (facet && String(row[facet.field]) !== facet.value) return false;
    if (!q.trim()) return true;
    if (serverMatches) return serverMatches.has(String(row["object_uid"]));
    const hay = Object.entries(row)
      .filter(([k]) => !BASE.has(k))
      .map(([, v]) => String(v ?? ""))
      .join(" ")
      .toLowerCase();
    return hay.includes(q.toLowerCase());
  });

  const open = (row: Row) => {
    const uid = row["object_uid"] as string | undefined;
    const ot = (row["object_type"] as string) || objectType || "";
    return uid && onOpenDetail ? () => onOpenDetail(ot, uid) : undefined;
  };

  return (
    <div className="search-block">
      <input
        type="search"
        className="search-input"
        placeholder="Filter by any field…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        aria-label="Search"
      />
      {facets.length > 0 && (
        <div className="facets" role="group" aria-label="Facets">
          {facets.map(([field, values]) =>
            values.map((v) => {
              const active = facet?.field === field && facet.value === v;
              return (
                <button
                  key={`${field}:${v}`}
                  type="button"
                  className={`chip${active ? " chip-active" : ""}`}
                  onClick={() => setFacet(active ? null : { field, value: v })}
                >
                  {fmtFieldName(field)}: {fmtValue(v)}
                </button>
              );
            }),
          )}
        </div>
      )}
      {filtered.length === 0 ? (
        <EmptyState title="No matches" hint="Try a different term or clear the facet filter." />
      ) : (
        <div className="card-grid">
          {filtered.map((row) => (
            <ObjectCard key={row["object_uid"] as string} row={row} onOpen={open(row)} />
          ))}
        </div>
      )}
    </div>
  );
}

function deriveFacets(rows: Row[]): [string, string[]][] {
  const distinct: Record<string, Set<string>> = {};
  for (const row of rows) {
    for (const [k, v] of Object.entries(row)) {
      if (BASE.has(k) || v === null || v === "") continue;
      if (typeof v === "object") continue;
      (distinct[k] ??= new Set()).add(String(v));
    }
  }
  return Object.entries(distinct)
    .filter(([, set]) => set.size >= 2 && set.size <= 6)
    .slice(0, 3)
    .map(([field, set]) => [field, [...set].sort()]);
}
