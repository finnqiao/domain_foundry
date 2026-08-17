import { useState } from "react";
import type { BlockProps } from "./kit";
import { EmptyState, ObjectCard, rowsOf } from "./kit";
import { api, ApiError } from "../lib/api";
import { fmtFieldName, fmtValue, rowTitle } from "../lib/format";
import type { Row } from "../lib/types";

type ListAction = {
  id?: string;
  label?: string;
  operation?: string;
  fields?: string[];
  field?: string;
};

export function ListBlock({ domain, view, data, onOpenDetail, onChanged }: BlockProps) {
  const rows = rowsOf(data);
  const groupBy = data["group_by"] as string | undefined;
  const groups = data["groups"] as Record<string, Row[]> | undefined;
  const objectType = data["object_type"] as string | undefined;
  const actions = (Array.isArray(view.config?.actions) ? view.config.actions : []).filter(
    (action): action is ListAction => typeof action === "object" && action !== null,
  );
  const action = actions.find((candidate) => candidate.operation === "update" && candidate.field);

  if (rows.length === 0) {
    return <EmptyState title="Nothing here yet" hint="Log something in this passion and it will appear on this list." />;
  }

  const open = (row: Row) => {
    const uid = row["object_uid"] as string | undefined;
    const ot = (row["object_type"] as string) || objectType || "";
    return uid && onOpenDetail ? () => onOpenDetail(ot, uid) : undefined;
  };

  const renderRow = (row: Row) => {
    const key = (row["object_uid"] as string | undefined) ?? rowTitle(row);
    return action ? (
      <ChecklistCard
        key={key}
        domain={domain}
        objectType={(row["object_type"] as string) || objectType || ""}
        row={row}
        action={action}
        onOpen={open(row)}
        onChanged={onChanged}
      />
    ) : <ObjectCard key={key} row={row} onOpen={open(row)} />;
  };

  if (groupBy && groups) {
    return (
      <div className="list-groups">
        {Object.entries(groups).map(([key, groupRows]) => (
          <div className="list-group" key={key}>
            <h4 className="group-label">
              {fmtFieldName(groupBy)}: {key} <span className="count-pill">{groupRows.length}</span>
            </h4>
            <div className="card-grid">
              {groupRows.map(renderRow)}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="card-grid">
      {rows.map(renderRow)}
    </div>
  );
}

function ChecklistCard({
  domain,
  objectType,
  row,
  action,
  onOpen,
  onChanged,
}: {
  domain: string;
  objectType: string;
  row: Row;
  action: ListAction;
  onOpen?: () => void;
  onChanged?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const field = action.field as string;
  const uid = row["object_uid"] as string | undefined;
  const checked = Boolean(row[field]);
  const shown = Object.keys(row).filter(
    (key) => !["id", "object_uid", "entry_id", "tombstoned", "created_at", "updated_at", field].includes(key),
  );

  async function toggle() {
    if (!uid || busy || !action.operation) return;
    setBusy(true);
    setError(null);
    try {
      await api.apply({
        domain,
        operation: action.operation,
        object_type: objectType,
        object_uid: uid,
        fields: { [field]: !checked },
      });
      onChanged?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That checklist item could not be updated.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card checklist-card">
      <button type="button" className="object-card-link" onClick={onOpen} disabled={!onOpen || !uid}>
        <span className="object-title">{rowTitle(row)}</span>
      </button>
      <dl className="kv">
        {shown.slice(0, 5).map((key) => (
          <div className="kv-row" key={key}>
            <dt>{fmtFieldName(key)}</dt>
            <dd>{fmtValue(row[key])}</dd>
          </div>
        ))}
      </dl>
      <button
        type="button"
        className={`check-toggle${checked ? " check-toggle-on" : ""}`}
        aria-pressed={checked}
        aria-label={`${action.label ?? field}: ${checked ? "packed" : "not packed"}`}
        disabled={busy || !uid}
        onClick={() => void toggle()}
      >
        <span className="check-toggle-mark" aria-hidden>{checked ? "✓" : ""}</span>
        {busy ? "Saving…" : `${action.label ?? fmtFieldName(field)}: ${checked ? "packed" : "not packed"}`}
      </button>
      {error && <p className="error">{error}</p>}
    </article>
  );
}
