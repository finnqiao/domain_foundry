import { FormEvent, useState } from "react";

type CaptureReceipt = {
  entry_id: string;
  status: string;
  summary?: string | null;
  idempotent_replay?: boolean;
};

export function App() {
  const [text, setText] = useState("");
  const [receipt, setReceipt] = useState<CaptureReceipt | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/capture", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, channel: "web" }),
      });
      if (!res.ok) {
        throw new Error(`capture failed (${res.status})`);
      }
      const data = (await res.json()) as CaptureReceipt;
      setReceipt(data);
      setText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <header className="brand">
        <h1>domain_expert</h1>
        <p>Describe your passion. Get an app. Talk to it.</p>
      </header>

      <section className="capture">
        <h2>Capture</h2>
        <p className="hint">
          No domains yet — captures land as ledger-only until packs and routing arrive
          (P2). Empty states that teach ship with the full shell in P5.
        </p>
        <form onSubmit={onSubmit}>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="baked a 75% hydration country loaf…"
            rows={4}
            required
          />
          <button type="submit" disabled={busy || !text.trim()}>
            {busy ? "Capturing…" : "Capture"}
          </button>
        </form>
        {error && <p className="error">{error}</p>}
        {receipt && (
          <pre className="receipt">{JSON.stringify(receipt, null, 2)}</pre>
        )}
      </section>
    </main>
  );
}
