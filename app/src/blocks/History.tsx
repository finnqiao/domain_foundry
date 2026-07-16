import type { BlockProps } from "./kit";
import { EmptyState, ObjectCard } from "./kit";
import type { Row } from "../lib/types";

type Period = { period: string; count: number; rows: Row[] };

export function History({ data, onOpenDetail }: BlockProps) {
  const periods = (data["periods"] as Period[]) || [];
  const granularity = (data["granularity"] as string) || "month";
  const objectType = data["object_type"] as string | undefined;
  if (periods.length === 0) {
    return (
      <EmptyState
        title="No history yet"
        hint="Past activity is grouped here by period once you start capturing."
      />
    );
  }
  const open = (row: Row) => {
    const uid = row["object_uid"] as string | undefined;
    const ot = (row["object_type"] as string) || objectType || "";
    return uid && onOpenDetail ? () => onOpenDetail(ot, uid) : undefined;
  };
  return (
    <div className="history-block">
      <p className="history-legend">Grouped by {granularity}</p>
      {periods.map((p) => (
        <div className="history-period" key={p.period}>
          <div className="history-period-head">
            <span className="history-period-label">{p.period}</span>
            <span className="count-pill">{p.count}</span>
          </div>
          <div className="card-grid">
            {p.rows.map((row) => (
              <ObjectCard key={row["object_uid"] as string} row={row} onOpen={open(row)} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
