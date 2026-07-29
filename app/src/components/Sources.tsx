import { useEffect, useState } from "react";
import { api, ApiError, type IngestReport } from "../lib/api";
import type { PackCard } from "../lib/types";

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
    <section className="panel">
      <h2>Add a source</h2>
      <p className="muted" style={{ marginTop: -4 }}>
        Pull notes and logs you already have into your foundries. Nothing at the source is moved
        or changed — preview first, it writes nothing.
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
              <Bar name="unfiled" n={report.unfiled} pct={Math.round((report.unfiled / max) * 100)} unfiled />
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
