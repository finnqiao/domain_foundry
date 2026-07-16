import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { fmtAge, fmtFieldName, fmtValue } from "../lib/format";
import type { PackCard, ReviewItem, ReviewStats } from "../lib/types";
import { EmptyState } from "./kit";
import { CorrectionDialog } from "../components/CorrectionDialog";

// Global review queue (plan §9.1, §3.4 backlog lesson): pending approvals with
// proposed-vs-canonical diff previews, approve / deny / edit-then-approve, bulk
// triage, and SLO counters.
export function ReviewQueue({ packs, refreshKey, onChanged }: { packs: PackCard[]; refreshKey: number; onChanged: () => void }) {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<ReviewItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      const [it, st] = await Promise.all([api.review(), api.reviewStats()]);
      setItems(it);
      setStats(st);
      setSelected(new Set());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  async function resolveOne(id: string, decision: string) {
    setBusy(true);
    try {
      await api.resolve(id, decision);
      await load();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function bulk(decision: string) {
    if (selected.size === 0) return;
    setBusy(true);
    try {
      await api.bulkResolve([...selected], decision);
      await load();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  if (err) return <p className="error">{err}</p>;
  if (!items || !stats) return <p className="muted">Loading…</p>;

  return (
    <div className="review-queue">
      <div className="slo-bar">
        <Slo label="Pending" value={stats.pending} />
        <Slo label="Overdue" value={stats.overdue} warn={stats.overdue > 0} />
        <Slo label="Oldest" value={fmtAge(stats.oldest_pending_age_seconds)} />
      </div>

      {items.length === 0 ? (
        <EmptyState
          title="Review queue is clear"
          hint="Nothing awaiting a decision. Confidence-gated captures apply automatically; only ambiguous or sensitive ones land here."
        />
      ) : (
        <>
          <div className="bulk-bar">
            <label className="bulk-select-all">
              <input
                type="checkbox"
                checked={selected.size === items.length && items.length > 0}
                onChange={(e) => setSelected(e.target.checked ? new Set(items.map((i) => i.approval_id)) : new Set())}
              />
              {selected.size > 0 ? `${selected.size} selected` : "Select all"}
            </label>
            <div className="bulk-actions">
              <button className="btn-secondary" disabled={busy || selected.size === 0} onClick={() => bulk("deny")}>
                Deny selected
              </button>
              <button className="btn-primary" disabled={busy || selected.size === 0} onClick={() => bulk("approve")}>
                Approve selected
              </button>
            </div>
          </div>

          <ul className="review-list">
            {items.map((it) => (
              <li className={`review-item${it.overdue ? " overdue" : ""}`} key={it.approval_id}>
                <label className="review-check">
                  <input
                    type="checkbox"
                    checked={selected.has(it.approval_id)}
                    onChange={() => toggle(it.approval_id)}
                    aria-label={`Select ${it.summary ?? it.approval_id}`}
                  />
                </label>
                <div className="review-content">
                  <div className="review-head">
                    <span className="badge badge-domain">{it.domain}</span>
                    <span className="badge">{it.operation}</span>
                    {it.object_type && <span className="review-obj">{it.object_type}</span>}
                    {it.confidence != null && <span className="badge badge-conf">{(it.confidence * 100).toFixed(0)}%</span>}
                    <span className="review-age">{fmtAge(it.age_seconds)} old</span>
                    {it.overdue && <span className="badge badge-fallback">overdue</span>}
                  </div>
                  {it.summary && <p className="review-summary">{it.summary}</p>}
                  {it.diff && <DiffTable diff={it.diff} />}
                  <div className="review-actions">
                    <button className="btn-tiny" disabled={busy} onClick={() => resolveOne(it.approval_id, "deny")}>
                      Deny
                    </button>
                    <button className="btn-tiny" disabled={busy || !it.object_uid} onClick={() => setEditing(it)}>
                      Edit &amp; approve
                    </button>
                    <button className="btn-tiny btn-tiny-primary" disabled={busy} onClick={() => resolveOne(it.approval_id, "approve")}>
                      Approve
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {editing && (
        <CorrectionDialog
          target={{
            objectUid: editing.object_uid ?? undefined,
            domain: editing.domain ?? undefined,
            objectType: editing.object_type ?? undefined,
            currentFields: Object.fromEntries(
              (editing.diff?.fields ?? []).map((f) => [f.field, f.proposed ?? f.current]),
            ),
          }}
          packs={packs}
          onClose={() => setEditing(null)}
          onDone={async () => {
            const id = editing.approval_id;
            setEditing(null);
            await resolveOne(id, "approve");
          }}
        />
      )}
    </div>
  );
}

function Slo({ label, value, warn }: { label: string; value: number | string; warn?: boolean }) {
  return (
    <div className={`slo${warn ? " slo-warn" : ""}`}>
      <span className="slo-value">{value}</span>
      <span className="slo-label">{label}</span>
    </div>
  );
}

function DiffTable({ diff }: { diff: NonNullable<ReviewItem["diff"]> }) {
  return (
    <table className="diff-table">
      <tbody>
        {diff.fields.map((f) => (
          <tr key={f.field} className={f.changed ? "diff-changed" : ""}>
            <th>{fmtFieldName(f.field)}</th>
            <td className="diff-current">{fmtValue(f.current)}</td>
            <td className="diff-arrow">→</td>
            <td className="diff-proposed">{fmtValue(f.proposed)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
