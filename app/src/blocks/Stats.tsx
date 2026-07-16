import type { BlockProps } from "./kit";
import { EmptyState } from "./kit";
import { fmtFieldName, fmtValue } from "../lib/format";

type Measure = {
  field: string;
  agg: string;
  distribution?: Record<string, number>;
  trend?: { at: string; value: number }[];
  count?: number;
};

export function Stats({ data }: BlockProps) {
  const measures = (data["measures"] as Measure[]) || [];
  const total = (data["total"] as number) ?? 0;
  if (total === 0 || measures.length === 0) {
    return <EmptyState title="No data to summarize yet" hint="Stats populate as objects accumulate." />;
  }
  return (
    <div className="stats-block">
      <p className="stats-total">
        <strong>{total}</strong> objects
      </p>
      {measures.map((m) => (
        <div className="measure" key={`${m.field}:${m.agg}`}>
          <h4 className="measure-title">
            {fmtFieldName(m.field)} <span className="measure-agg">{m.agg}</span>
          </h4>
          {m.distribution && <Distribution dist={m.distribution} />}
          {m.trend && <Trend trend={m.trend} />}
          {m.count !== undefined && !m.distribution && !m.trend && (
            <p className="measure-count">{m.count}</p>
          )}
        </div>
      ))}
    </div>
  );
}

function Distribution({ dist }: { dist: Record<string, number> }) {
  const entries = Object.entries(dist).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, n]) => n));
  return (
    <div className="dist">
      {entries.map(([label, n]) => (
        <div className="dist-row" key={label}>
          <span className="dist-label">{fmtValue(label)}</span>
          <span className="dist-bar-track">
            <span className="dist-bar" style={{ width: `${(n / max) * 100}%` }} />
          </span>
          <span className="dist-count">{n}</span>
        </div>
      ))}
    </div>
  );
}

function Trend({ trend }: { trend: { at: string; value: number }[] }) {
  const values = trend.map((t) => Number(t.value)).filter((v) => !Number.isNaN(v));
  if (values.length === 0) return <p className="measure-count">—</p>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return (
    <div className="trend">
      <div className="sparkline" aria-hidden>
        {values.map((v, i) => (
          <span key={i} className="spark-bar" style={{ height: `${8 + ((v - min) / span) * 32}px` }} />
        ))}
      </div>
      <p className="trend-meta">
        min {fmtValue(min)} · max {fmtValue(max)} · latest {fmtValue(values[values.length - 1])}
      </p>
    </div>
  );
}
