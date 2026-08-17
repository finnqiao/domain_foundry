import { useCallback, useEffect, useState } from "react";
import type { BlockProps } from "./kit";
import { EmptyState } from "./kit";
import { api, ApiError } from "../lib/api";
import { fmtDate } from "../lib/format";
import type { QuizActivity, QuizSession, ScheduleStatus } from "../lib/types";

type QuizStatsPayload = {
  domain?: string;
  due_count?: number;
  reviewed_today?: number;
  streak_days?: number;
  grade_distribution?: Record<string, number>;
  total_reviews?: number;
  review_count?: number;
};

/**
 * Pack-declared interactive session shell. The quiz mechanics remain behind
 * the existing mesh/HarnessAPI seam; this block only starts, resumes, grades,
 * and explains the durable local schedule state.
 */
export function QuizStats({ data, domain }: BlockProps) {
  const [remote, setRemote] = useState<QuizStatsPayload | null>(null);
  const [session, setSession] = useState<(QuizSession & { active?: boolean }) | null>(null);
  const [activity, setActivity] = useState<QuizActivity | null>(null);
  const [schedule, setSchedule] = useState<ScheduleStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setErr(null);
    try {
      const [stats, next, history, schedules] = await Promise.all([
        api.quizStats(domain),
        api.quizNext(domain),
        api.quizActivity(domain),
        api.schedules(domain),
      ]);
      setRemote(stats as QuizStatsPayload);
      setSession(next);
      setActivity(history);
      setSchedule(schedules);
    } catch (error) {
      setErr(error instanceof ApiError ? error.message : String(error));
    }
  }, [domain]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const payload: QuizStatsPayload = {
    ...(typeof data === "object" && data ? (data as QuizStatsPayload) : {}),
    ...(remote || {}),
  };
  const totalReviews = payload.total_reviews ?? payload.review_count ?? 0;
  const dist = payload.grade_distribution || {};
  const entries = Object.entries(dist).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, n]) => n));
  const currentSchedule = schedule?.schedules[0];
  const activeSession = session;
  const canGrade = Boolean(activeSession?.active && activeSession.prompt && activeSession.session_id);

  async function start() {
    setBusy(true);
    setErr(null);
    try {
      setSession(await api.quizStart({ domain }));
      await refresh();
    } catch (error) {
      setErr(error instanceof ApiError ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function grade(value: string) {
    if (!session?.session_id) return;
    setBusy(true);
    setErr(null);
    try {
      await api.quizGrade(domain, value, session.session_id);
      await refresh();
    } catch (error) {
      setErr(error instanceof ApiError ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function toggleSchedule() {
    if (!currentSchedule || currentSchedule.status === "revoked") return;
    setBusy(true);
    setErr(null);
    try {
      const nextStatus = currentSchedule.status === "paused" ? "active" : "paused";
      await api.setScheduleStatus(domain, currentSchedule.id, nextStatus);
      await refresh();
    } catch (error) {
      setErr(error instanceof ApiError ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="quiz-surface">
      {err && <p className="error" role="alert">{err}</p>}
      {totalReviews === 0 && !payload.due_count && entries.length === 0 ? (
        <EmptyState title="No reviews yet" hint="Start a session to populate review history." />
      ) : (
        <div className="stats-block quiz-stats-block">
          <div className="quiz-stats-kpis">
            <p><strong>{payload.due_count ?? "—"}</strong> due</p>
            <p><strong>{payload.reviewed_today ?? 0}</strong> today</p>
            <p><strong>{payload.streak_days ?? 0}</strong> day streak</p>
            <p><strong>{totalReviews}</strong> reviews</p>
          </div>
          {entries.length > 0 && (
            <div className="dist">
              {entries.map(([label, n]) => (
                <div className="dist-row" key={label}>
                  <span className="dist-label">{label}</span>
                  <span className="dist-bar-track"><span className="dist-bar" style={{ width: `${(n / max) * 100}%` }} /></span>
                  <span className="dist-count">{n}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <section className="quiz-session-panel" aria-label="Review session">
        <div className="section-head compact">
          <div>
            <h3>Review session</h3>
            <p className="muted">Sessions save progress locally and can resume after leaving this view.</p>
          </div>
          {session?.active && <span className="badge badge-ok">in progress</span>}
        </div>
        {canGrade && activeSession ? (
          <>
            <p className="quiz-prompt">{activeSession.prompt}</p>
            <div className="quiz-grade-actions" aria-label="Grade answer">
              {["again", "hard", "good", "easy"].map((value) => (
                <button key={value} className="btn" type="button" disabled={busy} onClick={() => void grade(value)}>
                  {value}
                </button>
              ))}
            </div>
            <p className="muted quiz-progress">Card {(activeSession.index ?? 0) + 1} of {activeSession.total}</p>
          </>
        ) : (
          <button className="btn btn-primary" type="button" disabled={busy} onClick={() => void start()}>
            {busy ? "Starting…" : "Start a session"}
          </button>
        )}
      </section>

      {currentSchedule && (
        <section className="quiz-schedule-panel" aria-label="Review schedule">
          <div className="section-head compact">
            <div>
              <h3>Review schedule</h3>
              <p className="muted">{currentSchedule.cron} · {currentSchedule.timezone ?? "timezone not declared"}</p>
            </div>
            <span className={`badge ${currentSchedule.status === "active" ? "badge-ok" : "badge-preview"}`}>
              {currentSchedule.status}
            </span>
          </div>
          <p className="muted">Missed-run policy: {currentSchedule.missed_run_policy ?? "not declared"}. Local evaluation is visible here; no calendar or notification provider is claimed.</p>
          {currentSchedule.next_due_at && <p className="quiz-progress">Next evaluated window: {fmtDate(currentSchedule.next_due_at)}</p>}
          {currentSchedule.status !== "revoked" && (
            <button className="btn" type="button" disabled={busy} onClick={() => void toggleSchedule()}>
              {currentSchedule.status === "paused" ? "Resume schedule" : "Pause schedule"}
            </button>
          )}
        </section>
      )}

      {activity && activity.sessions.length > 0 && (
        <section className="quiz-history-panel" aria-label="Session history">
          <h3>Session history</h3>
          <ul className="quiz-history-list">
            {activity.sessions.slice(0, 5).map((item) => (
              <li key={item.id}>
                <strong>{item.status}</strong>
                <span className="muted">{fmtDate(item.updated_at)} · {item.state.grades?.length ?? 0} grades</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
