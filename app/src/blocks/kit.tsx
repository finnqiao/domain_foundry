import type { ReactNode } from "react";
import type { BlockData, PackView, Row } from "../lib/types";
import { fmtFieldName, fmtValue, rowTitle } from "../lib/format";

// The contract every block component receives. Blocks are pure views over
// data served by /api/blocks/<view>/data — they never touch SQL (plan §9.2).
export type BlockProps = {
  domain: string;
  view: PackView;
  data: BlockData;
  onOpenDetail?: (objectType: string, uid: string) => void;
  onChanged?: () => void;
};

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty" role="status">
      <p className="empty-title">{title}</p>
      {hint && <p className="empty-hint">{hint}</p>}
    </div>
  );
}

// A compact, clickable card for a single domain object row.
export function ObjectCard({
  row,
  fields,
  onOpen,
}: {
  row: Row;
  fields?: string[];
  onOpen?: () => void;
}) {
  const uid = row["object_uid"] as string | undefined;
  const shown = (fields ?? Object.keys(row)).filter(
    (k) => !["id", "object_uid", "entry_id", "tombstoned", "created_at", "updated_at"].includes(k),
  );
  return (
    <button
      type="button"
      className="card object-card"
      onClick={onOpen}
      disabled={!onOpen || !uid}
      aria-label={`Open ${rowTitle(row)}`}
    >
      <span className="object-title">{rowTitle(row)}</span>
      <dl className="kv">
        {shown.slice(0, 6).map((k) => (
          <div className="kv-row" key={k}>
            <dt>{fmtFieldName(k)}</dt>
            <dd>{fmtValue(row[k])}</dd>
          </div>
        ))}
      </dl>
    </button>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="block-section">
      {title && <h3 className="block-heading">{title}</h3>}
      {children}
    </section>
  );
}

export function rowsOf(data: BlockData): Row[] {
  return (data["rows"] as Row[] | undefined) ?? [];
}
