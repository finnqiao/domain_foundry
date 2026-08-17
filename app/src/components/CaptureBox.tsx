import { useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import type { CaptureReceipt } from "../lib/types";

const STATUS_LABELS: Record<string, string> = {
  applied: "Filed",
  review: "Waiting for your review",
  ledger_only: "Saved — not filed anywhere yet (fix in Review)",
  unfiled: "Saved — not filed anywhere yet (fix in Review)",
};

// Global capture box. Capture-first: the raw text is durably stored before any
// interpretation, then routed. The receipt shows where it landed.
export function CaptureBox({ onCaptured }: { onCaptured: (r: CaptureReceipt) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState<CaptureReceipt | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.capture(text);
      setReceipt(r);
      setText("");
      onCaptured(r);
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : String(e2));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="capture-box" onSubmit={submit}>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void submit(e);
        }}
        placeholder="Capture anything… e.g. “baked a 75% hydration country loaf, bulk 5h, came out great”"
        rows={2}
        aria-label="Capture text"
      />
      <div className="capture-row">
        <span className="capture-kbd">⌘/Ctrl + Enter</span>
        <button type="submit" className="btn-primary" disabled={busy || !text.trim()}>
          {busy ? "Capturing…" : "Capture"}
        </button>
      </div>
      {err && <p className="error">{err}</p>}
      {receipt && (
        <div className="capture-receipt" role="status">
          <span className={`badge status-${receipt.status}`}>
            {STATUS_LABELS[receipt.status] ?? receipt.status}
          </span>
          {receipt.routed
            .filter((s) => s.domain)
            .map((s, i) => (
              <span key={i} className="badge badge-domain">
                {s.domain} · {s.object_type} · {s.disposition}
              </span>
            ))}
          {receipt.routed.every((s) => !s.domain) && (
            <span className="muted">
              Saved safely. Install a matching domain and captures like this will be filed
              automatically.
            </span>
          )}
        </div>
      )}
    </form>
  );
}
