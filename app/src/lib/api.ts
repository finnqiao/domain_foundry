// Thin typed client over the harness HTTP API. The app shell is a client of
// the harness with no privileged write path (plan §9.4): every mutation goes
// through capture() / correct() / review endpoints.

import type {
  BlockData,
  CaptureReceipt,
  CatalogEntry,
  CorrectionReceipt,
  EntryRow,
  EvalReport,
  HealthReport,
  ObjectDetail,
  PackCard,
  PackView,
  ReviewItem,
  ReviewStats,
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

export const api = {
  capture: (text: string, channel = "web") =>
    req<CaptureReceipt>("/api/capture", {
      method: "POST",
      body: JSON.stringify({ text, channel }),
    }),

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
  evalRouting: () => req<EvalReport>("/api/eval"),
};
