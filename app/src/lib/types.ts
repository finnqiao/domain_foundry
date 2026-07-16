// Shared API types — mirror the FastAPI shapes in core/domain_expert_core/api.

export type EntryStatus = "applied" | "review" | "ledger_only" | "unfiled";

export type RoutedSpan = {
  domain: string | null;
  object_type: string | null;
  operation: string | null;
  disposition: string;
  confidence: number | null;
};

export type CaptureReceipt = {
  entry_id: string;
  capture_event_id: string;
  status: EntryStatus;
  routed: RoutedSpan[];
  projection_status: string;
  idempotent_replay: boolean;
  summary?: string | null;
};

export type EntryRow = {
  id: string;
  capture_event_id: string;
  status: EntryStatus;
  domain: string | null;
  object_type: string | null;
  operation: string | null;
  routing_confidence: number | null;
  fallback_tier: string | null;
  summary: string | null;
  raw_text: string | null;
  channel: string | null;
  created_at: string;
  updated_at: string;
};

export type PackView = { id: string; title: string; block: string };

export type PackCard = {
  name: string;
  title: string;
  description: string;
  icon: string;
  version: string;
  objects: string[];
  views: PackView[];
  object_count: number;
};

export type CatalogEntry = {
  name: string;
  title: string;
  description: string;
  icon: string;
  version: string;
  installed: boolean;
};

export type BlockData = Record<string, unknown> & { block?: string };

export type Row = Record<string, unknown>;

export type ReviewItem = {
  approval_id: string;
  change_request_id: number;
  decision_status: string;
  application_status: string;
  domain: string | null;
  operation: string | null;
  object_type: string | null;
  object_uid: string | null;
  summary: string | null;
  confidence: number | null;
  created_at: string;
  age_seconds: number | null;
  overdue?: boolean;
  diff?: DiffPreview;
};

export type DiffField = {
  field: string;
  current: unknown;
  proposed: unknown;
  changed: boolean;
};

export type DiffPreview = {
  operation: string;
  object_uid: string | null;
  is_new: boolean;
  fields: DiffField[];
};

export type ReviewStats = {
  pending: number;
  overdue: number;
  oldest_pending_age_seconds: number | null;
  by_domain: Record<string, number>;
};

export type Revision = {
  revision: number;
  changed_fields: Record<string, { from: unknown; to: unknown }>;
  actor: string;
  actor_channel: string | null;
  created_at: string;
};

export type Interpretation = {
  version: number;
  interpreter: string;
  confidence: number | null;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type ObjectDetail = {
  object_uid: string;
  domain: string;
  object_type: string;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  fields: Record<string, unknown>;
  revisions: Revision[];
  capture: {
    entry_id: string;
    raw_text: string | null;
    channel: string | null;
    captured_at: string | null;
    status: string;
    routing_confidence: number | null;
  } | null;
  interpretations: Interpretation[];
  links: { relation: string; to_uid: string; confidence: number }[];
};

export type StoreHealth = {
  path: string;
  exists: boolean;
  ok: boolean;
  integrity: string;
  fk_violations: unknown[];
  schema_version: number;
};

export type HealthReport = {
  ok: boolean;
  ledger: StoreHealth;
  domains: StoreHealth;
  entry_counts: Record<string, number>;
  last_capture_at: string | null;
  projection_lag: {
    pending: number;
    failed: number;
    oldest_pending_age_seconds: number | null;
    by_adapter: Record<string, unknown>;
  };
  llm_spend?: { today_usd: number; daily_cap_usd: number };
};

export type EvalReport = {
  total: number;
  correct: number;
  accuracy: number;
  by_tag: Record<string, { correct: number; total: number }>;
};

export type CorrectionReceipt = {
  action: string;
  object_uid: string | null;
  revision: number | null;
  applied: boolean;
  error: string | null;
  details?: Record<string, unknown>;
};
