import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { fmtDate } from "../lib/format";
import type { EntryRow, PackCard } from "../lib/types";
import { EmptyState } from "./kit";
import { CorrectionDialog, type CorrectionTarget } from "../components/CorrectionDialog";

const STATUS_LABEL: Record<string, string> = {
  applied: "applied",
  review: "in review",
  ledger_only: "ledger only",
  unfiled: "unfiled",
};

// Global capture feed (plan §9.1): reverse-chron entries with routing badges +
// one-tap correction ("wrong domain?").
export function CaptureFeed({ packs, refreshKey }: { packs: PackCard[]; refreshKey: number }) {
  const [rows, setRows] = useState<EntryRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [correct, setCorrect] = useState<CorrectionTarget | null>(null);

  async function load() {
    try {
      setRows(await api.query({ limit: 50 }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  if (err) return <p className="error">{err}</p>;
  if (!rows) return <p className="muted">Loading…</p>;
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No captures yet"
        hint="Use the capture box above — every message is stored raw before it is interpreted."
      />
    );
  }

  return (
    <div className="feed">
      {rows.map((r) => (
        <article className="feed-item" key={r.id}>
          <div className="feed-body">
            <p className="feed-text">{r.raw_text || r.summary}</p>
            <div className="feed-badges">
              <span className={`badge status-${r.status}`}>{STATUS_LABEL[r.status] ?? r.status}</span>
              {r.domain && <span className="badge badge-domain">{r.domain}</span>}
              {r.routing_confidence != null && (
                <span className="badge badge-conf">{(r.routing_confidence * 100).toFixed(0)}%</span>
              )}
              {r.fallback_tier && r.fallback_tier !== "ledger_only" && (
                <span className="badge badge-fallback">{r.fallback_tier}</span>
              )}
              <span className="feed-time">{fmtDate(r.created_at)}</span>
            </div>
          </div>
          <button
            className="btn-tiny"
            onClick={() =>
              setCorrect({ entryId: r.id, domain: r.domain ?? undefined, objectType: r.object_type ?? undefined })
            }
            aria-label="Correct this capture"
          >
            Wrong?
          </button>
        </article>
      ))}
      {correct && (
        <CorrectionDialog
          target={correct}
          packs={packs}
          onClose={() => setCorrect(null)}
          onDone={() => {
            setCorrect(null);
            void load();
          }}
        />
      )}
    </div>
  );
}
