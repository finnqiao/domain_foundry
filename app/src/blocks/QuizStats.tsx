import { useEffect, useState } from "react";
import type { BlockProps } from "./kit";
import { EmptyState } from "./kit";

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
 * SRS quiz aggregates from HarnessAPI.quiz_stats (Phase 4).
 * Fetches `/api/quiz/stats` when embedded in the SPA; falls back to block data.
 */
export function QuizStats({ data, domain }: BlockProps & { domain?: string }) {
  const [remote, setRemote] = useState<QuizStatsPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const q = domain ? `?domain=${encodeURIComponent(domain)}` : "";
    fetch(`/api/quiz/stats${q}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then((j) => {
        if (!cancelled) setRemote(j as QuizStatsPayload);
      })
      .catch((e: Error) => {
        if (!cancelled) setErr(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [domain]);

  const payload: QuizStatsPayload = {
    ...(typeof data === "object" && data ? (data as QuizStatsPayload) : {}),
    ...(remote || {}),
  };

  const totalReviews = payload.total_reviews ?? payload.review_count ?? 0;
  const dist = payload.grade_distribution || {};
  if (totalReviews === 0 && !payload.due_count && Object.keys(dist).length === 0) {
    return (
      <EmptyState
        title={err ? `Quiz stats unavailable (${err})` : "No reviews yet"}
        hint="Complete a Japanese quiz to populate SRS stats."
      />
    );
  }

  const entries = Object.entries(dist).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, n]) => n));

  return (
    <div className="stats-block quiz-stats-block">
      <div className="quiz-stats-kpis">
        <p>
          <strong>{payload.due_count ?? "—"}</strong> due
        </p>
        <p>
          <strong>{payload.reviewed_today ?? 0}</strong> today
        </p>
        <p>
          <strong>{payload.streak_days ?? 0}</strong> day streak
        </p>
        <p>
          <strong>{totalReviews}</strong> reviews
        </p>
      </div>
      {entries.length > 0 && (
        <div className="dist">
          {entries.map(([label, n]) => (
            <div className="dist-row" key={label}>
              <span className="dist-label">{label}</span>
              <span className="dist-bar-track">
                <span className="dist-bar" style={{ width: `${(n / max) * 100}%` }} />
              </span>
              <span className="dist-count">{n}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
