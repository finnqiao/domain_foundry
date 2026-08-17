// Thin typed client over the harness HTTP API. The app shell is a client of
// the harness with no privileged write path (plan §9.4): every mutation goes
// through capture() / correct() / review endpoints.

import type {
  BlockData,
  AskResponse,
  CaptureReceipt,
  CatalogEntry,
  CorrectionReceipt,
  EntryRow,
  EvalReport,
  HealthReport,
  ObjectDetail,
  PackCard,
  PackView,
  ProvidersStatus,
  ApplyResult,
  HardeningResult,
  RoamboardReport,
  RoamboardShadow,
  PackImportReport,
  ReviewItem,
  ReviewStats,
  SearchResult,
  WizardTurn,
  QuizActivity,
  QuizSession,
  ScheduleStatus,
} from "./types";

// A bearer token can be injected at build/runtime for non-local binds.
const TOKEN = (window as unknown as { __DE_TOKEN__?: string }).__DE_TOKEN__;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (TOKEN) headers["Authorization"] = `Bearer ${TOKEN}`;
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export interface IngestBody {
  path: string;
  only?: string | null;
  split?: string;
  glob?: string;
  limit?: number;
}

export interface IngestReport {
  path: string;
  channel: string;
  split: string;
  dry_run: boolean;
  scanned: number;
  captured: number;
  skipped_existing: number;
  review: number;
  unfiled: number;
  filtered_out: number;
  by_domain: Record<string, number>;
}

export const api = {
  capture: (
    text: string,
    options: { channel?: string; domainHint?: string } | string = {},
  ) => {
    const opts = typeof options === "string" ? { channel: options } : options;
    return req<CaptureReceipt>("/api/capture", {
      method: "POST",
      body: JSON.stringify({
        text,
        channel: opts.channel ?? "web",
        domain_hint: opts.domainHint ?? null,
      }),
    });
  },

  query: (params: { q?: string; domain?: string; status?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.q) qs.set("q", params.q);
    if (params.domain) qs.set("domain", params.domain);
    if (params.status) qs.set("status", params.status);
    qs.set("limit", String(params.limit ?? 50));
    return req<{ rows: EntryRow[] }>(`/api/query?${qs.toString()}`).then((r) => r.rows);
  },

  packs: () => req<{ packs: PackCard[] }>("/api/packs").then((r) => r.packs),
  catalog: () => req<{ catalog: CatalogEntry[] }>("/api/packs/catalog").then((r) => r.catalog),
  activatePack: (name: string) =>
    req<{ name: string }>("/api/packs/activate", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  blockViews: (domain: string) =>
    req<{ views: PackView[] }>(`/api/blocks/${domain}/views`).then((r) => r.views),
  blockData: (domain: string, viewId: string, limit = 100) =>
    req<BlockData>(`/api/blocks/${domain}/${viewId}/data?limit=${limit}`),

  objectDetail: (domain: string, objectType: string, uid: string) =>
    req<ObjectDetail>(`/api/objects/${domain}/${objectType}/${encodeURIComponent(uid)}`),

  correct: (body: {
    text?: string;
    entry_id?: string;
    object_uid?: string;
    action?: string;
    fields?: Record<string, unknown>;
    merge_into_uid?: string;
    target_domain?: string;
  }) =>
    req<CorrectionReceipt>("/api/correct", {
      method: "POST",
      body: JSON.stringify({ ...body, channel: "web" }),
    }),

  review: (params: { status?: string; domain?: string; overdue_only?: boolean } = {}) => {
    const qs = new URLSearchParams({ include_diff: "true" });
    if (params.status) qs.set("status", params.status);
    if (params.domain) qs.set("domain", params.domain);
    if (params.overdue_only) qs.set("overdue_only", "true");
    return req<{ items: ReviewItem[] }>(`/api/review?${qs.toString()}`).then((r) => r.items);
  },
  reviewStats: () => req<ReviewStats>("/api/review/stats"),
  resolve: (approvalId: string, decision: string, note?: string) =>
    req(`/api/review/${approvalId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ decision, note }),
    }),
  bulkResolve: (approvalIds: string[], decision: string) =>
    req<{ applied: number; failed: number; count: number }>("/api/review/bulk-resolve", {
      method: "POST",
      body: JSON.stringify({ approval_ids: approvalIds, decision }),
    }),

  health: () => req<HealthReport>("/api/health"),
  providers: () => req<ProvidersStatus>("/api/settings/providers"),
  ask: async (
    question: string,
    options: { domain?: string; limit?: number } = {},
  ): Promise<AskResponse> => {
    try {
      return await req<AskResponse>("/api/ask", {
        method: "POST",
        body: JSON.stringify({
          question,
          domain: options.domain ?? null,
          limit: options.limit ?? 20,
        }),
      });
    } catch (error) {
      // If an older daemon is missing /api/ask, fall back to read-only search
      // and label the answer as search-only.
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      const rows = await api.query({ q: question, domain: options.domain, limit: options.limit ?? 20 });
      return {
        question,
        answer: rows.length ? "Closest matches from your captured data:" : "I don't have that in your captured data yet.",
        citations: rows.slice(0, 5).map((row) => ({
          object_uid: null,
          entry_id: row.id,
          domain: row.domain,
          object_type: row.object_type,
          snippet: row.raw_text ?? row.summary ?? "",
        })),
        mode: rows.length ? "search_only" : "refusal",
        cap_hit: false,
      };
    }
  },
  searchLedger: (query: string, options: { domain?: string; objectType?: string; kind?: "entry" | "canonical" } = {}) => {
    const qs = new URLSearchParams({ q: query });
    if (options.domain) qs.set("domain", options.domain);
    if (options.objectType) qs.set("object_type", options.objectType);
    if (options.kind) qs.set("kind", options.kind);
    return req<SearchResult>(`/api/search?${qs.toString()}`);
  },
  refileEntry: (entryId: string, domain: string) =>
    req<{ applied: boolean; entry_id: string; domain: string; status: string; error?: string }>(
      `/api/entries/${encodeURIComponent(entryId)}/refile`,
      { method: "POST", body: JSON.stringify({ domain }) },
    ),
  evalRouting: () => req<EvalReport>("/api/eval"),
  quizStats: (domain: string) =>
    req<{
      domain: string;
      due_count?: number;
      reviewed_today?: number;
      streak_days?: number;
      grade_distribution?: Record<string, number>;
      total_reviews?: number;
      review_count?: number;
    }>(`/api/quiz/stats?domain=${encodeURIComponent(domain)}`),
  quizStart: (options: { domain?: string; limit?: number } = {}) =>
    req<QuizSession>("/api/quiz/start", {
      method: "POST",
      body: JSON.stringify({ domain: options.domain ?? "japanese", limit: options.limit ?? null }),
    }),
  quizNext: (domain: string, userId = "default") =>
    req<QuizSession & { active: boolean }>(
      `/api/quiz/next?domain=${encodeURIComponent(domain)}&user_id=${encodeURIComponent(userId)}`,
    ),
  quizGrade: (domain: string, grade: string, sessionId?: string) =>
    req<QuizSession & { grade: string; done: boolean }>("/api/quiz/grade", {
      method: "POST",
      body: JSON.stringify({ domain, grade, session_id: sessionId ?? null }),
    }),
  quizActivity: (domain: string) =>
    req<QuizActivity>(`/api/quiz/activity?domain=${encodeURIComponent(domain)}`),
  schedules: (domain: string) =>
    req<ScheduleStatus>(`/api/schedules?domain=${encodeURIComponent(domain)}`),
  setScheduleStatus: (domain: string, scheduleId: string, status: string) =>
    req<{ domain: string; schedule_id: string; status: string }>(
      `/api/schedules/${encodeURIComponent(domain)}/${encodeURIComponent(scheduleId)}/status`,
      { method: "POST", body: JSON.stringify({ status }) },
    ),

  // Bolt existing notes/logs onto foundries. Preview is read-only; commit pulls
  // in. Both are local, server-side operations (distinct from the sealed write
  // path) — see docs/tutorial/adopt-in-place.md.
  ingestPreview: (body: IngestBody) =>
    req<IngestReport>("/api/ingest/preview", { method: "POST", body: JSON.stringify(body) }),
  ingestCommit: (body: IngestBody) =>
    req<IngestReport>("/api/ingest", { method: "POST", body: JSON.stringify(body) }),

  roamboardPreview: (feedPath: string) =>
    req<RoamboardReport>("/api/import/roamboard/preview", {
      method: "POST",
      body: JSON.stringify({ feed_path: feedPath }),
    }),
  roamboardCommit: (feedPath: string, previewToken: string) =>
    req<RoamboardReport>("/api/import/roamboard/commit", {
      method: "POST",
      body: JSON.stringify({ feed_path: feedPath, preview_token: previewToken }),
    }),
  roamboardShadow: () => req<RoamboardShadow>("/api/import/roamboard/shadow"),

  packImportMappings: (domain: string) =>
    req<{ mappings: Record<string, unknown>[] }>(
      `/api/import/pack/${encodeURIComponent(domain)}/mappings`,
    ).then((r) => r.mappings),
  packImportPreview: (body: { domain: string; mapping_id: string; source_path?: string }) =>
    req<PackImportReport>("/api/import/pack/preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  packImportCommit: (body: {
    domain: string;
    mapping_id: string;
    source_path?: string;
    preview_token: string;
  }) =>
    req<PackImportReport>("/api/import/pack/commit", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  apply: (body: {
    domain: string;
    operation: string;
    object_type: string;
    fields: Record<string, unknown>;
    object_uid?: string;
    entry_id?: string;
  }) => req<ApplyResult>("/api/apply", { method: "POST", body: JSON.stringify(body) }),

  hardeningPreview: (domain: string, text: string) =>
    req<HardeningResult>(`/api/domains/${encodeURIComponent(domain)}/hardening/preview`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  hardeningApply: (domain: string, text: string) =>
    req<HardeningResult>(`/api/domains/${encodeURIComponent(domain)}/hardening/apply`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  hardeningRollback: (domain: string) =>
    req<HardeningResult>(`/api/domains/${encodeURIComponent(domain)}/rollback`, { method: "POST" }),

  wizardStart: (goal: string) =>
    req<WizardTurn>("/api/wizard", {
      method: "POST",
      body: JSON.stringify({ goal_text: goal }),
    }),
  wizardReply: (sessionId: string, text: string) =>
    req<WizardTurn>(`/api/wizard/${encodeURIComponent(sessionId)}/reply`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  wizardSuggest: (domain: string) =>
    req<{ suggestion: { suggestion?: string; idea_id?: string; apply_edit?: string } | null }>(
      `/api/wizard/${encodeURIComponent(domain)}/suggest`,
    ),
};
