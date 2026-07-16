import type { BlockProps } from "./kit";
import { EmptyState, rowsOf } from "./kit";
import { fmtDate, fmtValue, rowTitle } from "../lib/format";
import type { Row } from "../lib/types";

export function Timeline({ data, onOpenDetail }: BlockProps) {
  const rows = rowsOf(data);
  const dateField = (data["date_field"] as string) || "created_at";
  const objectType = data["object_type"] as string | undefined;
  if (rows.length === 0) {
    return (
      <EmptyState
        title="Nothing on the timeline yet"
        hint="Capture something above and it will appear here, newest first."
      />
    );
  }
  return (
    <ol className="timeline">
      {rows.map((row: Row) => {
        const uid = row["object_uid"] as string | undefined;
        const ot = (row["object_type"] as string) || objectType || "";
        return (
          <li className="timeline-item" key={uid ?? Math.random()}>
            <time className="timeline-date">{fmtDate(row[dateField] as string)}</time>
            <button
              type="button"
              className="timeline-card"
              onClick={uid && onOpenDetail ? () => onOpenDetail(ot, uid) : undefined}
              disabled={!uid || !onOpenDetail}
            >
              <span className="timeline-title">{rowTitle(row)}</span>
              <span className="timeline-sub">
                {Object.entries(row)
                  .filter(
                    ([k, v]) =>
                      !["id", "object_uid", "entry_id", "tombstoned", "created_at", "updated_at", dateField].includes(
                        k,
                      ) && v !== null && v !== "",
                  )
                  .slice(0, 3)
                  .map(([k, v]) => `${k}: ${fmtValue(v)}`)
                  .join("  ·  ")}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
