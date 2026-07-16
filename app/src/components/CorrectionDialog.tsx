import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { fmtFieldName, fmtValue } from "../lib/format";
import type { PackCard } from "../lib/types";

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
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

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
        if (!mergeUid) throw new Error("Enter the survivor object UID");
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
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Correct">
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
            <label className="field-row">
              <span>Merge into (survivor UID)</span>
              <input
                value={mergeUid}
                placeholder="object_uid of the survivor"
                onChange={(e) => setMergeUid(e.target.value)}
              />
            </label>
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
