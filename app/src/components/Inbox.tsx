import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { EntryRow, PackCard, ReviewItem } from "../lib/types";
import { EmptyState } from "../blocks/kit";
import { DiffTable } from "../blocks/DiffTable";
import { CorrectionDialog, type CorrectionTarget } from "./CorrectionDialog";

export function Inbox({
  packs,
  refreshKey,
  onChanged,
}: {
  packs: PackCard[];
  refreshKey: number;
  onChanged: () => void;
}) {
  const [review, setReview] = useState<ReviewItem[] | null>(null);
  const [unfiled, setUnfiled] = useState<EntryRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<ReviewItem | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [reviewItems, unfiledRows] = await Promise.all([
        api.review(),
        api.query({ status: "unfiled", limit: 100 }),
      ]);
      setReview(reviewItems);
      setUnfiled(unfiledRows);
      setSelected(new Set());
    } catch (error) {
      setErr(error instanceof Error ? error.message : String(error));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  async function resolve(approvalId: string, decision: string) {
    setBusy(approvalId);
    try {
      await api.resolve(approvalId, decision);
      await load();
      onChanged();
    } catch (error) {
      setErr(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function refile(entry: EntryRow, domain: string) {
    setBusy(`${entry.id}:${domain}`);
    setErr(null);
    try {
      await api.refileEntry(entry.id, domain);
      await load();
      onChanged();
    } catch (error) {
      const message = error instanceof ApiError ? error.message : String(error);
      setErr(`Couldn't file that passion yet: ${message}`);
    } finally {
      setBusy(null);
    }
  }

  async function dismiss(entry: EntryRow) {
    setBusy(entry.id);
    setErr(null);
    try {
      await api.correct({ entry_id: entry.id, action: "mark_wrong" });
      await load();
      onChanged();
    } catch (error) {
      setErr(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function bulkResolve(decision: string) {
    if (selected.size === 0) return;
    setBusy("bulk");
    try {
      await api.bulkResolve([...selected], decision);
      await load();
      onChanged();
    } catch (error) {
      setErr(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  if (err && !review && !unfiled) return <p className="error" role="alert">{err}</p>;
  if (!review || !unfiled) return <p className="muted">Loading your Inbox…</p>;

  const isEmpty = review.length === 0 && unfiled.length === 0;
  return (
    <div className="inbox">
      <section className="surface-intro">
        <div>
          <h1>Inbox</h1>
          <p className="muted">A short list of things that need your judgment.</p>
        </div>
        <span className="today-count">{review.length + unfiled.length} to review</span>
      </section>

      {err && <p className="error" role="alert">{err}</p>}
      {isEmpty && (
        <EmptyState
          title="Nothing needs your attention"
          hint="Confident captures file themselves. If something is ambiguous, it will wait here for you."
        />
      )}

      {review.length > 0 && (
        <section className="attention-section" aria-labelledby="review-heading">
          <div className="section-head">
            <div>
              <h2 id="review-heading">Waiting for your OK</h2>
              <p className="muted">These captures are saved, but haven’t changed a passion yet.</p>
            </div>
            <button className="btn-secondary" type="button" onClick={() => setSelectMode((open) => !open)}>
              {selectMode ? "Hide bulk actions" : "Select several…"}
            </button>
          </div>
          {selectMode && (
            <div className="bulk-bar">
              <label className="bulk-select-all">
                <input
                  type="checkbox"
                  checked={selected.size === review.length}
                  onChange={(event) => setSelected(event.target.checked ? new Set(review.map((item) => item.approval_id)) : new Set())}
                />
                {selected.size > 0 ? `${selected.size} selected` : "Select all"}
              </label>
              <div className="bulk-actions">
                <button className="btn-secondary" type="button" disabled={!selected.size || busy !== null} onClick={() => void bulkResolve("deny")}>
                  Don't save
                </button>
                <button className="btn-primary" type="button" disabled={!selected.size || busy !== null} onClick={() => void bulkResolve("approve")}>
                  Save selected
                </button>
              </div>
            </div>
          )}
          <ul className="attention-list">
            {review.map((item) => (
              <li className="attention-row" key={item.approval_id}>
                {selectMode && (
                  <input
                    type="checkbox"
                    checked={selected.has(item.approval_id)}
                    onChange={() => {
                      const next = new Set(selected);
                      if (next.has(item.approval_id)) next.delete(item.approval_id);
                      else next.add(item.approval_id);
                      setSelected(next);
                    }}
                    aria-label={`Select ${item.summary ?? "capture"}`}
                  />
                )}
                <div className="attention-copy">
                  <p>
                    I read “{item.summary ?? "this capture"}” as {article(item.object_type)} {humanType(item.object_type)} in {packTitle(packs, item.domain)}. OK to save it?
                  </p>
                  {item.diff && <DiffTable diff={item.diff} />}
                  <div className="attention-actions">
                    <button className="btn-tiny" type="button" disabled={busy !== null} onClick={() => void resolve(item.approval_id, "deny")}>
                      Don’t
                    </button>
                    <button className="btn-tiny" type="button" disabled={busy !== null} onClick={() => setEditing(item)}>
                      Fix first
                    </button>
                    <button className="btn-tiny btn-tiny-primary" type="button" disabled={busy !== null} onClick={() => void resolve(item.approval_id, "approve")}>
                      Save it
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {unfiled.length > 0 && (
        <section className="attention-section" aria-labelledby="unfiled-heading">
          <div className="section-head">
            <div>
              <h2 id="unfiled-heading">Couldn’t file these</h2>
              <p className="muted">Choose the passion that feels right. The original note stays attached.</p>
            </div>
          </div>
          <ul className="attention-list">
            {unfiled.map((entry) => (
              <li className="attention-row" key={entry.id}>
                <div className="attention-copy">
                  <p>“{entry.raw_text ?? entry.summary ?? "Untitled entry"}” — I wasn’t sure where this belongs.</p>
                  <div className="refile-actions" aria-label="Choose a passion">
                    {packs.map((pack) => (
                      <button
                        key={pack.name}
                        type="button"
                        className="chip passion-chip"
                        disabled={busy !== null}
                        onClick={() => void refile(entry, pack.name)}
                      >
                        <span aria-hidden>{pack.icon}</span> {pack.title}
                      </button>
                    ))}
                    <button className="btn-tiny" type="button" disabled={busy !== null} onClick={() => void dismiss(entry)}>
                      Not important
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {editing && (
        <CorrectionDialog
          target={reviewTarget(editing)}
          packs={packs}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null);
            void resolve(editing.approval_id, "approve");
          }}
        />
      )}
    </div>
  );
}

function packTitle(packs: PackCard[], domain: string | null): string {
  return packs.find((pack) => pack.name === domain)?.title ?? domain ?? "your passions";
}

function humanType(value: string | null): string {
  return (value ?? "entry").replace(/_/g, " ");
}

function article(value: string | null): string {
  return /^[aeiou]/i.test(humanType(value)) ? "an" : "a";
}

function reviewTarget(item: ReviewItem): CorrectionTarget {
  return {
    objectUid: item.object_uid ?? undefined,
    entryId: undefined,
    domain: item.domain ?? undefined,
    objectType: item.object_type ?? undefined,
    currentFields: Object.fromEntries(
      (item.diff?.fields ?? []).map((field) => [field.field, field.proposed ?? field.current]),
    ),
  };
}
