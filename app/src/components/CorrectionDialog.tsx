import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { fmtFieldName, fmtValue } from "../lib/format";
import type { PackCard, SearchHit } from "../lib/types";

export type CorrectionTarget = {
  entryId?: string;
  objectUid?: string;
  domain?: string;
  objectType?: string;
  currentFields?: Record<string, unknown>;
};

type Action = "amend" | "move" | "merge" | "undo" | "mark_wrong";

// Correction dialog — every action calls correct() (plan §9.4). The shell has
// no privileged write path: move/merge/amend all round-trip through the same
// path as a chat correction.
export function CorrectionDialog({
  target,
  packs,
  onClose,
  onDone,
}: {
  target: CorrectionTarget;
  packs: PackCard[];
  onClose: () => void;
  onDone: () => void;
}) {
  const canAmend = !!target.objectUid && !!target.currentFields;
  const [action, setAction] = useState<Action>(canAmend ? "amend" : "move");
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(target.currentFields ?? {}).map(([k, v]) => [k, v == null ? "" : String(v)]),
    ),
  );
  const [targetDomain, setTargetDomain] = useState("");
  const [mergeUid, setMergeUid] = useState("");
  const [mergeQuery, setMergeQuery] = useState("");
  const [candidates, setCandidates] = useState<SearchHit[]>([]);
  const [mergeError, setMergeError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    restoreRef.current = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    dialog?.querySelector<HTMLElement>("button:not([disabled]), input, select, textarea")?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key === "Tab" && dialog) {
        const elements = [...dialog.querySelectorAll<HTMLElement>(
          "button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
        )];
        if (elements.length === 0) return;
        const first = elements[0];
        const last = elements[elements.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          last.focus();
          e.preventDefault();
        } else if (!e.shiftKey && document.activeElement === last) {
          first.focus();
          e.preventDefault();
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      restoreRef.current?.focus();
    };
  }, [onClose]);

  useEffect(() => {
    if (action !== "merge" || mergeQuery.trim().length < 2 || !target.domain || !target.objectType) {
      setCandidates([]);
      setMergeError(null);
      return;
    }
    const timer = window.setTimeout(() => {
      setMergeError(null);
      void api
        .searchLedger(mergeQuery, {
          domain: target.domain,
          objectType: target.objectType,
          kind: "canonical",
        })
        .then((result) => setCandidates(result.hits.filter((hit) => hit.ref_id !== target.objectUid)))
        .catch((error) => {
          setCandidates([]);
          setMergeError(error instanceof Error ? "Record search is not available in this server build yet." : String(error));
        });
    }, 200);
    return () => window.clearTimeout(timer);
  }, [action, mergeQuery, target.domain, target.objectType, target.objectUid]);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      if (action === "amend") {
        const changed: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(fields)) {
          const orig = target.currentFields?.[k];
          if (String(orig ?? "") !== v) changed[k] = coerce(v, orig);
        }
        if (Object.keys(changed).length === 0) {
          setErr("No fields changed.");
          setBusy(false);
          return;
        }
        await api.correct({ object_uid: target.objectUid, entry_id: target.entryId, action: "amend", fields: changed });
      } else if (action === "move") {
        if (!targetDomain) throw new Error("Pick a target domain");
        await api.correct({
          object_uid: target.objectUid,
          entry_id: target.entryId,
          action: "move",
          target_domain: targetDomain,
        });
      } else if (action === "merge") {
        if (!mergeUid) throw new Error("Choose the record to keep");
        await api.correct({ object_uid: target.objectUid, action: "merge", merge_into_uid: mergeUid });
      } else if (action === "undo") {
        await api.correct({ object_uid: target.objectUid, entry_id: target.entryId, action: "undo" });
      } else {
        await api.correct({ object_uid: target.objectUid, entry_id: target.entryId, action: "mark_wrong" });
      }
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <div ref={dialogRef} className="modal" role="dialog" aria-modal="true" aria-label="Correct">
        <header className="modal-head">
          <h2>Correct</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="seg" role="tablist" aria-label="Correction type">
          {(["amend", "move", "merge", "undo", "mark_wrong"] as Action[]).map((a) => {
            const disabled =
              (a === "amend" && !canAmend) ||
              ((a === "merge" || a === "undo") && !target.objectUid);
            return (
              <button
                key={a}
                role="tab"
                aria-selected={action === a}
                className={`seg-btn${action === a ? " seg-active" : ""}`}
                disabled={disabled}
                onClick={() => setAction(a)}
              >
                {a === "mark_wrong" ? "mark wrong" : a}
              </button>
            );
          })}
        </div>

        <div className="modal-body">
          {action === "amend" && (
            <div className="field-editor">
              {Object.keys(fields).length === 0 && <p className="muted">No editable fields.</p>}
              {Object.entries(fields).map(([k, v]) => (
                <label className="field-row" key={k}>
                  <span>{fmtFieldName(k)}</span>
                  <input value={v} onChange={(e) => setFields({ ...fields, [k]: e.target.value })} />
                </label>
              ))}
            </div>
          )}
          {action === "move" && (
            <label className="field-row">
              <span>Move to domain</span>
              <select value={targetDomain} onChange={(e) => setTargetDomain(e.target.value)}>
                <option value="">Choose…</option>
                {packs
                  .filter((p) => p.name !== target.domain)
                  .map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.icon} {p.title}
                    </option>
                  ))}
              </select>
            </label>
          )}
          {action === "merge" && (
            <div className="field-row merge-picker">
              <span>Merge into</span>
              <input
                type="search"
                value={mergeQuery}
                placeholder={`Search ${target.objectType ?? "records"}…`}
                aria-label="Search for the record to keep"
                onChange={(e) => setMergeQuery(e.target.value)}
              />
              {mergeQuery.trim().length < 2 && <p className="muted">Type at least two characters to find a record.</p>}
              {mergeError && <p className="muted">{mergeError}</p>}
              {candidates.length > 0 && (
                <ul className="merge-candidates" role="listbox" aria-label="Merge candidates">
                  {candidates.map((candidate) => (
                    <li key={candidate.ref_id}>
                      <button
                        type="button"
                        role="option"
                        aria-selected={mergeUid === candidate.ref_id}
                        className={`chip${mergeUid === candidate.ref_id ? " chip-active" : ""}`}
                        onClick={() => setMergeUid(candidate.ref_id)}
                      >
                        {candidate.snippet ?? candidate.canonical_text ?? candidate.ref_id}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {mergeUid && <p className="muted">Keeping the selected record.</p>}
            </div>
          )}
          {action === "undo" && (
            <p className="muted">
              Appends a reverting revision (tombstone) — history is preserved, nothing is deleted.
            </p>
          )}
          {action === "mark_wrong" && (
            <p className="muted">
              Records this as a known-bad interpretation. It feeds the eval corpus without applying a fix.
            </p>
          )}
          {target.currentFields && action === "amend" && (
            <details className="current-values">
              <summary>Current values</summary>
              <dl className="kv">
                {Object.entries(target.currentFields).map(([k, v]) => (
                  <div className="kv-row" key={k}>
                    <dt>{fmtFieldName(k)}</dt>
                    <dd>{fmtValue(v)}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
        </div>

        {err && <p className="error">{err}</p>}
        <footer className="modal-foot">
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={submit} disabled={busy}>
            {busy ? "Applying…" : "Apply correction"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function coerce(value: string, original: unknown): unknown {
  if (typeof original === "number") {
    const n = Number(value);
    return Number.isNaN(n) ? value : n;
  }
  if (typeof original === "boolean") return value === "true" || value === "yes";
  return value;
}
