import { useEffect, useState } from "react";
import { api, ApiError, type IngestReport } from "../lib/api";
import type { PackCard, RoamboardReport, RoamboardShadow } from "../lib/types";

// "Add a source": bolt existing notes/logs onto foundries. Preview is read-only;
// Pull in commits. Same non-destructive, idempotent engine as `domain-foundry
// ingest` and the standalone /sources page.
export function Sources() {
  const [packs, setPacks] = useState<PackCard[]>([]);
  const [path, setPath] = useState("");
  const [only, setOnly] = useState("");
  const [split, setSplit] = useState("file");
  const [report, setReport] = useState<IngestReport | null>(null);
  const [committed, setCommitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.packs().then(setPacks).catch(() => setPacks([]));
  }, []);

  async function run(commit: boolean) {
    if (!path.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const body = { path: path.trim(), only: only || null, split };
      const rep = commit ? await api.ingestCommit(body) : await api.ingestPreview(body);
      setReport(rep);
      setCommitted(commit);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't read that path — check the folder exists.");
    } finally {
      setBusy(false);
    }
  }

  const domains = report ? Object.entries(report.by_domain) : [];
  const max = Math.max(1, ...domains.map(([, n]) => n), report?.unfiled ?? 0);

  return (
    <>
      <section className="panel">
        <h2>Add a source</h2>
        <p className="muted" style={{ marginTop: -4 }}>
          Pull notes you already have into a passion. Your original files are never moved
          or changed — preview first; it writes nothing until you confirm.
        </p>

        <div className="sources-form">
          <label className="sources-label" htmlFor="src-path">
            Folder or file to pull in
          </label>
          <input
            id="src-path"
            className="sources-input"
            placeholder="~/Notes/climbing"
            spellCheck={false}
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run(false)}
          />
          <div className="sources-row">
            <div>
              <label className="sources-label" htmlFor="src-only">
                Only this foundry <span className="muted">(optional)</span>
              </label>
              <select id="src-only" className="sources-input" value={only} onChange={(e) => setOnly(e.target.value)}>
                <option value="">Let the models pick</option>
                {packs.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.title || p.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="sources-label" htmlFor="src-split">
                Each file is
              </label>
              <select id="src-split" className="sources-input" value={split} onChange={(e) => setSplit(e.target.value)}>
                <option value="file">one note</option>
                <option value="lines">an append-only log (one per line)</option>
              </select>
            </div>
          </div>
          <div className="sources-actions">
            <button className="btn" disabled={busy || !path.trim()} onClick={() => run(false)}>
              Preview routing
            </button>
            <button className="btn btn-primary" disabled={busy || !report} onClick={() => run(true)}>
              Pull in
            </button>
          </div>
          <p className="muted sources-hint">
            Preview reads your files read-only and shows where each note would land. Re-running “Pull
            in” only picks up what’s new.
          </p>
        </div>

        {error && <p className="sources-error">{error}</p>}

        {report && (
          <div className="sources-result">
            <span className={`badge ${committed ? "badge-ok" : "badge-preview"}`}>
              {committed ? "pulled in ✓" : "preview · nothing written"}
            </span>
            <div className="sources-stats">
              <Stat n={report.scanned} label="scanned" />
              <Stat
                n={committed ? report.captured : report.scanned - report.unfiled - report.filtered_out}
                label={committed ? "captured" : "would file"}
              />
              {report.filtered_out > 0 && <Stat n={report.filtered_out} label="left alone" />}
              {committed && report.skipped_existing > 0 && <Stat n={report.skipped_existing} label="already had" />}
            </div>
            <div className="sources-bars">
              {domains.length === 0 && report.unfiled === 0 && (
                <p className="muted">No matches yet — try a different folder or foundry.</p>
              )}
              {domains.map(([name, n]) => (
                <Bar key={name} name={name} n={n} pct={Math.round((n / max) * 100)} />
              ))}
              {report.unfiled > 0 && (
                <Bar name="Couldn't file" n={report.unfiled} pct={Math.round((report.unfiled / max) * 100)} unfiled />
              )}
            </div>
            {!committed && (
              <p className="muted sources-hint">
                Looks right? Click <strong>Pull in</strong> to file these into your foundries.
              </p>
            )}
          </div>
        )}
      </section>
      <RoamboardPanel />
    </>
  );
}

function RoamboardPanel() {
  const [feedPath, setFeedPath] = useState("");
  const [report, setReport] = useState<RoamboardReport | null>(null);
  const [previewToken, setPreviewToken] = useState("");
  const [shadow, setShadow] = useState<RoamboardShadow | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadShadow() {
    try {
      setShadow(await api.roamboardShadow());
    } catch {
      setShadow(null);
    }
  }

  useEffect(() => {
    void loadShadow();
  }, []);

  async function preview() {
    if (!feedPath.trim()) return;
    setBusy(true);
    setError(null);
    setReport(null);
    setPreviewToken("");
    try {
      const next = await api.roamboardPreview(feedPath.trim());
      setReport(next);
      setPreviewToken(next.preview_token ?? "");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn’t preview that Roamboard feed.");
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!feedPath.trim() || !previewToken) return;
    setBusy(true);
    setError(null);
    try {
      setReport(await api.roamboardCommit(feedPath.trim(), previewToken));
      setPreviewToken("");
      await loadShadow();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn’t commit that Roamboard feed.");
    } finally {
      setBusy(false);
    }
  }

  const counts = report
    ? ([
        ["created", report.created],
        ["updated", report.updated],
        ["skipped", report.skipped],
        ["conflict", report.conflict],
        ["error", report.error],
      ] as const)
    : [];
  const streak = shadow?.streak;
  const zeroDiff = shadow?.report?.zero_diff === true;

  return (
    <section className="panel roamboard-panel">
      <div className="section-head compact">
        <div>
          <h2>Roamboard</h2>
          <p className="muted">Preview a schemaVersion 2 feed, then commit the exact bytes you reviewed.</p>
        </div>
        <span className="badge badge-preview">authenticated</span>
      </div>
      <label className="sources-label" htmlFor="roamboard-feed-path">
        Feed JSON path
      </label>
      <input
        id="roamboard-feed-path"
        className="sources-input"
        placeholder="~/Roamboard/feed.json"
        spellCheck={false}
        value={feedPath}
        onChange={(event) => {
          setFeedPath(event.target.value);
          setReport(null);
          setPreviewToken("");
        }}
        onKeyDown={(event) => event.key === "Enter" && void preview()}
      />
      <div className="sources-actions">
        <button className="btn" disabled={busy || !feedPath.trim()} onClick={() => void preview()}>
          {busy && !previewToken ? "Previewing…" : "Preview import"}
        </button>
        <button className="btn btn-primary" disabled={busy || !previewToken} onClick={() => void commit()}>
          {busy && previewToken ? "Committing…" : "Commit reviewed feed"}
        </button>
      </div>
      {error && <p className="sources-error">{error}</p>}

      {report && (
        <div className="roamboard-report" data-testid="roamboard-report">
          <div className="sources-stats">
            {counts.map(([label, value]) => <Stat key={label} n={value} label={label} />)}
          </div>
          <p className="muted roamboard-meta">
            {report.phase === "preview" ? "Nothing written." : "Committed."} · {report.accounted_for}/{report.source_total} accounted · fingerprint <code>{report.content_fingerprint.slice(0, 12)}</code>
          </p>
          <div className="roamboard-table-wrap">
            <table className="roamboard-table">
              <caption className="sr-only">Roamboard import records</caption>
              <thead><tr><th>Source</th><th>Entity</th><th>Outcome</th><th>Reason</th></tr></thead>
              <tbody>
                {report.records.map((record, index) => (
                  <tr key={`${record.source_ref ?? record.source_id ?? "record"}-${index}`}>
                    <td><code>{record.source_ref ?? String(record.source_id ?? "—")}</code></td>
                    <td>{record.entity ?? "—"}</td>
                    <td><span className={`outcome outcome-${record.outcome}`}>{record.outcome}</span></td>
                    <td>{record.reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details className="roamboard-raw">
            <summary>Raw adapter payload</summary>
            <pre className="code">{JSON.stringify(report.raw_adapter_payload, null, 2)}</pre>
          </details>
        </div>
      )}

      <div className="roamboard-shadow">
        <div className="section-head compact">
          <div>
            <h3>Shadow parity</h3>
            <p className="muted">Progress comes only from the latest persisted shadow report.</p>
          </div>
          {shadow?.available && <span className={`badge ${zeroDiff ? "badge-ok" : "badge-preview"}`}>{zeroDiff ? "zero diff" : "needs review"}</span>}
        </div>
        {streak ? (
          <>
            <progress className="shadow-progress" max={streak.target} value={Math.min(streak.days, streak.target)} aria-label="Roamboard zero-diff streak" />
            <p className="roamboard-streak"><strong>{streak.days}/{streak.target} days</strong> recorded · the seven-day gate remains human-verified.</p>
          </>
        ) : <p className="muted">No shadow report is available yet.</p>}
      </div>
    </section>
  );
}

function Stat({ n, label }: { n: number; label: string }) {
  return (
    <div className="sources-stat">
      <div className="sources-stat-n">{n}</div>
      <div className="sources-stat-l">{label}</div>
    </div>
  );
}

function Bar({ name, n, pct, unfiled }: { name: string; n: number; pct: number; unfiled?: boolean }) {
  return (
    <div className="sources-bar">
      <span className="sources-bar-name">{name}</span>
      <div className="sources-bar-track">
        <div className={`sources-bar-fill${unfiled ? " sources-bar-unfiled" : ""}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="sources-bar-cnt">{n}</span>
    </div>
  );
}
