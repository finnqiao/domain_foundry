import { useEffect, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { fmtAge, fmtDate } from "../lib/format";
import type { EvalReport, HealthReport } from "../lib/types";

// Operational health panel (plan §9.1): store integrity, projection lag, LLM
// spend, and a routing score you can run on demand.
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
  if (!health) return <p className="muted">Loading…</p>;

  const spend = health.llm_spend;
  const spendPct = spend ? Math.min(100, (spend.today_usd / spend.daily_cap_usd) * 100) : 0;

  return (
    <div className="health-panel">
      <div className="health-grid">
        <HealthCard title="Ledger store" ok={health.ledger.ok}>
          <p>Integrity: {health.ledger.integrity}</p>
          <p>FK violations: {health.ledger.fk_violations.length}</p>
          <p className="muted">schema v{health.ledger.schema_version}</p>
        </HealthCard>

        <HealthCard title="Domains store" ok={health.domains.ok}>
          <p>Integrity: {health.domains.integrity}</p>
          <p>FK violations: {health.domains.fk_violations.length}</p>
          <p className="muted">schema v{health.domains.schema_version}</p>
        </HealthCard>

        <HealthCard title="Projection lag" ok={health.projection_lag.failed === 0}>
          <p>Pending: {health.projection_lag.pending}</p>
          <p>Failed: {health.projection_lag.failed}</p>
          <p className="muted">
            oldest {fmtAge(health.projection_lag.oldest_pending_age_seconds)}
          </p>
        </HealthCard>

        <HealthCard title="LLM spend (today)" ok={spendPct < 100}>
          {spend ? (
            <>
              <p>
                ${spend.today_usd.toFixed(4)} / ${spend.daily_cap_usd.toFixed(2)} cap
              </p>
              <span className="dist-bar-track">
                <span className="dist-bar" style={{ width: `${spendPct}%` }} />
              </span>
            </>
          ) : (
            <p className="muted">n/a</p>
          )}
        </HealthCard>

        <HealthCard title="Routing score" ok={!evalReport || evalReport.accuracy >= 0.9}>
          {evalReport ? (
            <>
              <p className="score-big">{(evalReport.accuracy * 100).toFixed(0)}%</p>
              <p className="muted">
                {evalReport.correct}/{evalReport.total} eval cases
              </p>
            </>
          ) : (
            <button className="btn-secondary" onClick={runEval} disabled={evalBusy}>
              {evalBusy ? "Running…" : "Run eval"}
            </button>
          )}
        </HealthCard>

        <HealthCard title="Captures" ok>
          {Object.entries(health.entry_counts).map(([k, v]) => (
            <p key={k}>
              {k}: {v}
            </p>
          ))}
          <p className="muted">last {fmtDate(health.last_capture_at)}</p>
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
