import { useState, type FormEvent } from "react";
import type { BlockProps } from "./kit";
import { EmptyState, ObjectCard } from "./kit";
import { api, ApiError } from "../lib/api";
import type { Row } from "../lib/types";

// Future-dated items + a "plan next" affordance. Planning is still a capture
// (capture-first, invariant 1): the affordance sends NL text through capture(),
// never a privileged write.
export function Planner({ data, onOpenDetail, onChanged }: BlockProps) {
  const upcoming = (data["upcoming"] as Row[]) || [];
  const past = (data["past"] as Row[]) || [];
  const objectType = data["object_type"] as string | undefined;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const open = (row: Row) => {
    const uid = row["object_uid"] as string | undefined;
    const ot = (row["object_type"] as string) || objectType || "";
    return uid && onOpenDetail ? () => onOpenDetail(ot, uid) : undefined;
  };

  async function planNext(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await api.capture(text);
      setText("");
      onChanged?.();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : String(e2));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="planner-block">
      <form className="plan-next" onSubmit={planNext}>
        <input
          type="text"
          placeholder="Plan next… (e.g. “bake a rye loaf this weekend”)"
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label="Plan next item"
        />
        <button type="submit" disabled={busy || !text.trim()}>
          {busy ? "Adding…" : "Plan"}
        </button>
      </form>
      {err && <p className="error">{err}</p>}

      <h4 className="planner-heading">Upcoming</h4>
      {upcoming.length === 0 ? (
        <EmptyState title="Nothing planned ahead" hint="Use “Plan next” to add a future item." />
      ) : (
        <div className="card-grid">
          {upcoming.map((row) => (
            <ObjectCard key={row["object_uid"] as string} row={row} onOpen={open(row)} />
          ))}
        </div>
      )}

      {past.length > 0 && (
        <>
          <h4 className="planner-heading muted">Recent</h4>
          <div className="card-grid">
            {past.slice(0, 6).map((row) => (
              <ObjectCard key={row["object_uid"] as string} row={row} onOpen={open(row)} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
