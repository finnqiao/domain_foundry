import { useEffect, useState } from "react";
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
}: {
  target: DetailTarget;
  packs: PackCard[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<ObjectDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState(false);

  async function load() {
    setErr(null);
    try {
      setDetail(await api.objectDetail(target.domain, target.objectType, target.uid));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void load();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !correcting) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target.uid]);

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal modal-wide"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Object detail"
      >
        <header className="modal-head">
          <h2>{detail ? fmtFieldName(detail.object_type) : "Detail"}</h2>
          <div className="modal-head-actions">
            {detail && (
              <button className="btn-secondary" onClick={() => setCorrecting(true)}>
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
                      <li key={l.to_uid}>
                        <span className="badge">{l.relation}</span> {l.to_uid}
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
          onClose={() => setCorrecting(false)}
          onDone={() => {
            setCorrecting(false);
            void load();
            onChanged();
          }}
        />
      )}
    </div>
  );
}
