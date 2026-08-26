import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { fmtDate, fmtFieldName, fmtValue } from "../lib/format";
import type { ObjectDetail, PackCard } from "../lib/types";
import { CorrectionDialog } from "./CorrectionDialog";
import type { DetailTarget } from "../lib/nav";

// Detail block (plan §9.1) as a global overlay. Shows the object's fields, the
// full provenance chain — capture text → interpretation (confidence) →
// revisions — and its cross-domain links.
export function DetailModal({
  target,
  packs,
  onClose,
  onChanged,
  onOpenDetail,
}: {
  target: DetailTarget;
  packs: PackCard[];
  onClose: () => void;
  onChanged: () => void;
  onOpenDetail: (target: DetailTarget) => void;
}) {
  const [detail, setDetail] = useState<ObjectDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const correctingRef = useRef(false);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    correctingRef.current = correcting;
  }, [correcting]);

  const openCorrection = useCallback(() => {
    correctingRef.current = true;
    setCorrecting(true);
  }, []);

  const closeCorrection = useCallback(() => {
    correctingRef.current = false;
    setCorrecting(false);
  }, []);

  const load = useCallback(async () => {
    setErr(null);
    try {
      setDetail(await api.objectDetail(target.domain, target.objectType, target.uid));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [target.domain, target.objectType, target.uid]);

  useEffect(() => {
    void load();
    restoreRef.current = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    dialog?.querySelector<HTMLElement>("button:not([disabled]), [href], input, select, textarea")?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !correctingRef.current) onClose();
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
  }, [load, onClose]);

  return (
    <div className="modal-backdrop" role="presentation">
      <div
        ref={dialogRef}
        className="modal modal-wide"
        role="dialog"
        aria-modal="true"
        aria-label="Object detail"
      >
        <header className="modal-head">
          <h2>{detail ? fmtFieldName(detail.object_type) : "Detail"}</h2>
          <div className="modal-head-actions">
            {detail && (
              <button className="btn-secondary" onClick={openCorrection}>
                Correct
              </button>
            )}
            <button className="icon-btn" onClick={onClose} aria-label="Close">
              ✕
            </button>
          </div>
        </header>

        {err && <p className="error">{err}</p>}
        {!detail && !err && <p className="muted">Loading…</p>}

        {detail && (
          <div className="detail-grid">
            <section className="detail-main">
              <h3 className="block-heading">Fields</h3>
              <dl className="kv kv-lg">
                {Object.entries(detail.fields).map(([k, v]) => (
                  <div className="kv-row" key={k}>
                    <dt>{fmtFieldName(k)}</dt>
                    <dd>{fmtValue(v)}</dd>
                  </div>
                ))}
              </dl>
              {detail.links.length > 0 && (
                <>
                  <h3 className="block-heading">Links</h3>
                    <ul className="link-list">
                      {detail.links.map((l) => (
                        <li key={`${l.relation}-${l.to_uid}`}>
                          <span className="badge">{l.relation}</span>{" "}
                          {linkedTarget(l.to_uid, packs) ? (
                            <button
                              type="button"
                              className="detail-link"
                              onClick={() => {
                                const next = linkedTarget(l.to_uid, packs);
                                if (next) onOpenDetail(next);
                              }}
                            >
                              {l.to_uid}
                            </button>
                          ) : <span>{l.to_uid}</span>}
                        </li>
                      ))}
                  </ul>
                </>
              )}
            </section>

            <aside className="provenance">
              <h3 className="block-heading">Provenance</h3>
              <ol className="prov-chain">
                {detail.capture && (
                  <li className="prov-step">
                    <span className="prov-kind">Capture</span>
                    <p className="prov-text">“{detail.capture.raw_text}”</p>
                    <p className="prov-meta">
                      {detail.capture.channel} · {fmtDate(detail.capture.captured_at)}
                    </p>
                  </li>
                )}
                {detail.interpretations.map((i) => (
                  <li className="prov-step" key={i.version}>
                    <span className="prov-kind">
                      Interpretation v{i.version} <span className="badge">{i.interpreter}</span>
                    </span>
                    <p className="prov-meta">
                      {i.confidence != null && (
                        <span className="conf">confidence {(i.confidence * 100).toFixed(0)}%</span>
                      )}{" "}
                      · {i.status}
                    </p>
                  </li>
                ))}
                {detail.revisions.map((r) => (
                  <li className="prov-step" key={`rev-${r.revision}`}>
                    <span className="prov-kind">
                      Revision {r.revision} <span className="badge">{r.actor}</span>
                    </span>
                    <ul className="rev-fields">
                      {Object.entries(r.changed_fields).map(([f, d]) => (
                        <li key={f}>
                          <code>{f}</code>: {fmtValue(d.from)} → <strong>{fmtValue(d.to)}</strong>
                        </li>
                      ))}
                    </ul>
                    <p className="prov-meta">{fmtDate(r.created_at)}</p>
                  </li>
                ))}
              </ol>
            </aside>
          </div>
        )}
      </div>

      {correcting && detail && (
        <CorrectionDialog
          target={{
            objectUid: detail.object_uid,
            domain: detail.domain,
            objectType: detail.object_type,
            currentFields: detail.fields,
          }}
          packs={packs}
          onClose={closeCorrection}
          onDone={() => {
            closeCorrection();
            void load();
            onChanged();
          }}
        />
      )}
    </div>
  );
}

function linkedTarget(uid: string, packs: PackCard[]): DetailTarget | null {
  const [domain, objectType] = uid.split(":");
  if (!domain || !objectType) return null;
  const pack = packs.find((candidate) => candidate.name === domain);
  return pack?.objects.includes(objectType) ? { domain, objectType, uid } : null;
}
