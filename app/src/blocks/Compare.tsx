import { useEffect, useMemo, useState } from "react";
import type { BlockProps } from "./kit";
import { EmptyState } from "./kit";
import { fmtFieldName, fmtValue, rowTitle } from "../lib/format";
import type { Row } from "../lib/types";

type Metric = { id: string; label?: string; unit?: string };

export function Compare({ data, onOpenDetail }: BlockProps) {
  const rows = useMemo(
    () => (Array.isArray(data.rows) ? data.rows : []) as Row[],
    [data.rows],
  );
  const metrics = (Array.isArray(data.metrics) ? data.metrics : []) as Metric[];
  const selectionLimit = Number(data.selection_limit ?? 3);
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    setSelected(rows.slice(0, selectionLimit).map((row) => String(row.object_uid ?? "")).filter(Boolean));
  }, [rows, selectionLimit]);

  if (rows.length === 0) {
    return <EmptyState title="Nothing to compare yet" hint="Capture at least two records and choose them here." />;
  }

  const chosen = rows.filter((row) => selected.includes(String(row.object_uid)));
  function toggle(uid: string) {
    setSelected((current) => {
      if (current.includes(uid)) return current.filter((value) => value !== uid);
      return current.length >= selectionLimit ? current : [...current, uid];
    });
  }

  return (
    <div className="compare-block" data-testid="compare-block">
      <div className="compare-picker">
        <p className="muted">Choose up to {selectionLimit} records.</p>
        {rows.map((row) => {
          const uid = String(row.object_uid ?? "");
          return (
            <label key={uid} className="compare-choice">
              <input type="checkbox" checked={selected.includes(uid)} onChange={() => toggle(uid)} />
              <span>{rowTitle(row)}</span>
            </label>
          );
        })}
      </div>
      {chosen.length === 0 ? <p className="muted">Select a record to see its metrics.</p> : (
        <div className="compare-table-wrap">
          <table className="compare-table">
            <thead>
              <tr>
                <th scope="col">Measure</th>
                {chosen.map((row) => {
                  const uid = String(row.object_uid ?? "");
                  const objectType = String(row.object_type ?? data.object_type ?? "");
                  return (
                    <th scope="col" key={uid}>
                      {onOpenDetail ? <button type="button" className="detail-link" onClick={() => onOpenDetail(objectType, uid)}>{rowTitle(row)}</button> : rowTitle(row)}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {metrics.map((metric) => (
                <tr key={metric.id}>
                  <th scope="row">{metric.label ?? fmtFieldName(metric.id)}{metric.unit ? ` (${metric.unit})` : ""}</th>
                  {chosen.map((row) => <td key={String(row.object_uid)}>{fmtValue((row.derived as Record<string, unknown> | undefined)?.[metric.id])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
