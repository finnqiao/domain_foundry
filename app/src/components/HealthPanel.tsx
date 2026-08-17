import { useEffect, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { fmtAge, fmtDate } from "../lib/format";
import type { EvalReport, HealthReport } from "../lib/types";

// Status page for Settings → Health. Speak like a product status screen,
// not an operator console (ledger / FK / projection jargon stays off-screen).
export function HealthPanel({ refreshKey }: { refreshKey: number }) {
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [evalReport, setEvalReport] = useState<EvalReport | null>(null);
  const [evalBusy, setEvalBusy] = useState(false);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e) => setErr(String(e)));
  }, [refreshKey]);

  async function runEval() {
    setEvalBusy(true);
    try {
      setEvalReport(await api.evalRouting());
    } finally {
      setEvalBusy(false);
    }
  }

  if (err) return <p className="error">{err}</p>;
  if (!health) return <p className="muted">Checking your notes…</p>;

  const spend = health.llm_spend;
  const spendPct = spend ? Math.min(100, (spend.today_usd / spend.daily_cap_usd) * 100) : 0;
  const notesOk = health.ledger.ok && health.domains.ok;
  const viewsOk = health.projection_lag.failed === 0;
  const filed = health.entry_counts.applied ?? 0;
  const waiting =
    (health.entry_counts.unfiled ?? 0) + (health.entry_counts.review ?? 0);

  return (
    <div className="health-panel">
      <div className="health-grid">
        <HealthCard title="Your notes" ok={notesOk}>
          <p>{notesOk ? "Everything looks intact on this computer." : "Something needs attention in storage."}</p>
          <p className="muted">Local files only — nothing is uploaded.</p>
        </HealthCard>

        <HealthCard title="Your views" ok={viewsOk}>
          <p>
            {viewsOk
              ? health.projection_lag.pending === 0
                ? "Timelines and lists are up to date."
                : `${health.projection_lag.pending} update(s) still catching up.`
              : `${health.projection_lag.failed} view update(s) failed.`}
          </p>
          {health.projection_lag.oldest_pending_age_seconds != null && (
            <p className="muted">oldest wait {fmtAge(health.projection_lag.oldest_pending_age_seconds)}</p>
          )}
        </HealthCard>

        <HealthCard title="Model spend today" ok={spendPct < 100}>
          {spend ? (
            <>
              <p>
                ${spend.today_usd.toFixed(4)} / ${spend.daily_cap_usd.toFixed(2)} daily limit
              </p>
              <span className="dist-bar-track">
                <span className="dist-bar" style={{ width: `${spendPct}%` }} />
              </span>
            </>
          ) : (
            <p className="muted">No model configured — keyword filing only.</p>
          )}
        </HealthCard>

        <HealthCard title="Filing accuracy" ok={!evalReport || evalReport.accuracy >= 0.9}>
          {evalReport ? (
            <>
              <p className="score-big">{(evalReport.accuracy * 100).toFixed(0)}%</p>
              <p className="muted">
                {evalReport.correct}/{evalReport.total} sample notes filed correctly
              </p>
            </>
          ) : (
            <button className="btn-secondary" onClick={runEval} disabled={evalBusy}>
              {evalBusy ? "Checking…" : "Check filing"}
            </button>
          )}
        </HealthCard>

        <HealthCard title="Activity" ok>
          <p>Filed: {filed}</p>
          <p>Waiting in Inbox: {waiting}</p>
          <p className="muted">last note {fmtDate(health.last_capture_at)}</p>
        </HealthCard>
      </div>
    </div>
  );
}

function HealthCard({
  title,
  ok,
  children,
}: {
  title: string;
  ok: boolean;
  children: ReactNode;
}) {
  return (
    <div className={`health-card ${ok ? "ok" : "bad"}`}>
      <div className="health-card-head">
        <span className={`dot ${ok ? "dot-ok" : "dot-bad"}`} aria-hidden />
        <h3>{title}</h3>
      </div>
      <div className="health-card-body">{children}</div>
    </div>
  );
}
