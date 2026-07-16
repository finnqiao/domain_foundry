import type { BlockProps } from "./kit";
import { EmptyState, ObjectCard, rowsOf } from "./kit";
import { fmtFieldName } from "../lib/format";
import type { Row } from "../lib/types";

export function ListBlock({ data, onOpenDetail }: BlockProps) {
  const rows = rowsOf(data);
  const groupBy = data["group_by"] as string | undefined;
  const groups = data["groups"] as Record<string, Row[]> | undefined;
  const objectType = data["object_type"] as string | undefined;

  if (rows.length === 0) {
    return <EmptyState title="No items yet" hint="Captured objects in this domain will be listed here." />;
  }

  const open = (row: Row) => {
    const uid = row["object_uid"] as string | undefined;
    const ot = (row["object_type"] as string) || objectType || "";
    return uid && onOpenDetail ? () => onOpenDetail(ot, uid) : undefined;
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
              {groupRows.map((row) => (
                <ObjectCard key={row["object_uid"] as string} row={row} onOpen={open(row)} />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="card-grid">
      {rows.map((row) => (
        <ObjectCard key={row["object_uid"] as string} row={row} onOpen={open(row)} />
      ))}
    </div>
  );
}
