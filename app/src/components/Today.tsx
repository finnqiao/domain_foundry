import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { describeRow } from "../lib/receipts";
import type { EntryRow, PackCard } from "../lib/types";
import { useNav } from "../lib/nav";
import { EmptyState } from "../blocks/kit";
import { CorrectionDialog, type CorrectionTarget } from "./CorrectionDialog";
import { Composer } from "./Composer";

export function Today({ packs }: { packs: PackCard[] }) {
  const { navigate, refresh, refreshKey } = useNav();
  const [rows, setRows] = useState<EntryRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<CorrectionTarget | null>(null);

  useEffect(() => {
    let active = true;
    setRows(null);
    api
      .query({ limit: 20 })
      .then((nextRows) => {
        if (active) {
          setRows(nextRows);
          setErr(null);
        }
      })
      .catch((error) => {
        if (active) setErr(error instanceof Error ? error.message : String(error));
      });
    return () => {
      active = false;
    };
  }, [refreshKey]);

  return (
    <div className="today">
      <section className="surface-intro">
        <div>
          <h1>Today</h1>
          <p className="muted">Write something down, or ask what your records already know.</p>
        </div>
        {packs.length > 0 && <span className="today-count">{packs.length} passions</span>}
      </section>

      <Composer packs={packs} onDone={() => refresh()} />
      {packs[0] && <TodaySuggest domain={packs[0].name} />}

      <section className="activity-section" aria-labelledby="activity-heading">
        <div className="section-head">
          <div>
            <h2 id="activity-heading">Recent activity</h2>
            <p className="muted">Your latest entries, in the order they arrived.</p>
          </div>
          <button className="btn-secondary" type="button" onClick={() => navigate({ name: "inbox" })}>
            Open Inbox
          </button>
        </div>

        {err && <p className="error" role="alert">{err}</p>}
        {!rows && !err && <p className="muted">Loading recent activity…</p>}
        {rows && rows.length === 0 && (
          <EmptyState
            title={packs.length === 0 ? "Describe a passion and get an app" : "Nothing here yet"}
            hint={
              packs.length === 0
                ? "Start with a passion in your own words, or browse the starter catalog."
                : "Your saved entries will appear here after your first note."
            }
          >
            <div className="empty-actions">
              {packs.length === 0 && (
                <button className="btn-primary" type="button" onClick={() => navigate({ name: "create" })}>
                  Create your own
                </button>
              )}
              <button className="btn-secondary" type="button" onClick={() => navigate({ name: "passions" })}>
                Browse passions
              </button>
            </div>
          </EmptyState>
        )}
        {rows && rows.length > 0 && (
          <div className="activity-list">
            {rows.map((row) => {
              const description = describeRow(row, packs);
              const target: CorrectionTarget = {
                entryId: row.id,
                domain: row.domain ?? undefined,
                objectType: row.object_type ?? undefined,
              };
              const needsInbox = row.status === "unfiled" || row.status === "review";
              return (
                <article className="activity-row" key={row.id}>
                  <button
                    type="button"
                    className="activity-main"
                    onClick={() => {
                      if (needsInbox) navigate({ name: "inbox" });
                      else if (row.domain) navigate({ name: "domain", domain: row.domain });
                    }}
                    disabled={!needsInbox && !row.domain}
                  >
                    <span className="activity-copy">
                      <strong>{row.raw_text || row.summary || "Untitled entry"}</strong>
                      <span className="activity-receipt">{description.headline}</span>
                    </span>
                    <span className="activity-meta">
                      {row.domain && <span className="badge badge-domain">{packs.find((p) => p.name === row.domain)?.title ?? row.domain}</span>}
                      <time dateTime={row.created_at}>{formatActivityDate(row.created_at)}</time>
                    </span>
                  </button>
                  <button
                    type="button"
                    className="btn-tiny"
                    onClick={() => setCorrecting(target)}
                    aria-label={`Correct ${row.raw_text || row.summary || "entry"}`}
                  >
                    Wrong?
                  </button>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {correcting && (
        <CorrectionDialog
          target={correcting}
          packs={packs}
          onClose={() => setCorrecting(null)}
          onDone={() => {
            setCorrecting(null);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function formatActivityDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function TodaySuggest({ domain }: { domain: string }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    api
      .wizardSuggest(domain)
      .then((payload) => {
        if (active) setText(payload.suggestion?.suggestion ?? null);
      })
      .catch(() => {
        if (active) setText(null);
      });
    return () => {
      active = false;
    };
  }, [domain]);
  if (!text) return null;
  return (
    <aside className="suggest-banner" aria-label="Next idea">
      <p>{text}</p>
    </aside>
  );
}
