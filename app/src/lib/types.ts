// Shared API types — mirror the FastAPI shapes in core/domain_foundry_core/api.

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
  llm_error?: string | null;
  domain_hint?: string | null;
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

export type PackView = {
  id: string;
  title: string;
  block: string;
  object?: string;
  objects?: string[];
  config?: Record<string, unknown>;
};

export type PackCard = {
  name: string;
  title: string;
  description: string;
  icon: string;
  version: string;
  objects: string[];
  views: PackView[];
  accent?: string | null;
  object_count: number;
  status?: "scaffold" | "live" | string;
  capabilities?: Record<string, unknown>;
  compatibility?: { core?: string | null; capabilities?: Record<string, string> };
};

export type CatalogEntry = {
  name: string;
  title: string;
  description: string;
  icon: string;
  version: string;
  accent?: string | null;
  installed: boolean;
};

export type RoamboardRecord = {
  entity: string | null;
  source_ref: string | null;
  source_id: string | number | null;
  outcome: "created" | "updated" | "skipped" | "conflict" | "error" | string;
  reason: string | null;
  raw?: Record<string, unknown>;
};

export type RoamboardReport = {
  phase: "preview" | "commit" | string;
  feed_path: string;
  content_fingerprint: string;
  source_total: number;
  accounted_for: number;
  complete: boolean;
  created: number;
  updated: number;
  skipped: number;
  conflict: number;
  error: number;
  records: RoamboardRecord[];
  raw_adapter_payload: Record<string, unknown>;
  preview_token?: string;
  preview_expires_at?: string;
};

export type RoamboardShadow = {
  available: boolean;
  report: (Record<string, unknown> & { zero_diff?: boolean; report_dir?: string }) | null;
  streak: {
    days: number;
    target: number;
    complete: boolean;
    source: string | null;
    human_gate: boolean;
  };
};

export type PackImportOutcome = {
  entity: string;
  source_ref: string | null;
  source_id: string | number | null;
  kind: string;
  reason: string | null;
  object_uid?: string | null;
};

export type PackImportReport = {
  phase: "preview" | "commit" | string;
  domain: string;
  mapping_id: string;
  source_path: string;
  content_fingerprint: string;
  source_total: number;
  accounted_for: number;
  complete: boolean;
  imported: number;
  would_import: number;
  skipped_existing: number;
  skipped_invalid: number;
  failed: number;
  by_entity: Record<string, Record<string, number>>;
  outcomes: PackImportOutcome[];
  preview_token?: string;
  preview_expires_at?: string;
};

export type QuizSession = {
  session_id?: string;
  status?: string;
  total: number;
  index: number;
  prompt: string | null;
  card_uid?: string | null;
  done?: boolean;
  correct?: number;
};

export type QuizActivity = {
  domain: string;
  sessions: Array<{
    id: string;
    status: string;
    created_at: string;
    updated_at: string;
    state: { total?: number; correct?: number; grades?: string[] };
  }>;
};

export type ScheduleStatus = {
  domain: string;
  schedules: Array<{
    id: string;
    cron: string;
    status: "active" | "paused" | "revoked" | string;
    timezone?: string | null;
    missed_run_policy?: string | null;
    last_fired_at?: string | null;
    next_due_at?: string | null;
    fire_count?: number;
    human_gate?: boolean;
  }>;
};

export type ApplyResult = {
  ok: boolean;
  applied?: boolean;
  operation?: string;
  object_uid?: string | null;
  revision?: number | null;
  error?: string | null;
  [key: string]: unknown;
};

export type HardeningPlan = {
  domain: string;
  object: string;
  summary: string[];
  added: Array<{ name: string; sql_type: string }>;
  renamed: Array<{ from: string; to: string }>;
  migration_sql: string;
  ok: boolean;
  error: string | null;
};

export type HardeningResult = {
  domain: string;
  edit_text?: string;
  plan?: HardeningPlan;
  snapshot?: string;
  restored?: string;
  [key: string]: unknown;
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

export type AskCitation = {
  object_uid: string | null;
  entry_id: string | null;
  domain: string | null;
  object_type: string | null;
  snippet: string;
};

export type AskResponse = {
  question: string;
  answer: string;
  citations: AskCitation[];
  mode: "llm" | "search_only" | "refusal" | string;
  plan?: Record<string, unknown>;
  model?: string | null;
  cost_usd?: number;
  spend_today_usd?: number;
  daily_cap_usd?: number;
  cap_hit?: boolean;
};

export type SearchHit = {
  kind: "entry" | "canonical" | string;
  ref_id: string;
  domain: string | null;
  object_type: string | null;
  raw_text?: string | null;
  canonical_text?: string | null;
  snippet?: string | null;
  rank?: number;
};

export type SearchResult = {
  query: string;
  hits: SearchHit[];
  total: number;
};

export type ProviderTierStatus = {
  model: string | null;
  base_url: string | null;
  api_key_env: string | null;
  api_key_present: boolean;
  live: boolean;
};

export type ProvidersStatus = {
  config_file: string;
  config_file_exists: boolean;
  provider: string | null;
  mode: string | null;
  detected_env_keys: { provider: string; env: string }[];
  routine: ProviderTierStatus;
  sota: ProviderTierStatus;
};

export type WizardObject = {
  name: string;
  title_field?: string;
  fields?: string[];
};

export type WizardAcceptance = {
  passed?: number;
  routed?: number;
  total?: number;
  accuracy?: number;
  failures?: Array<Record<string, unknown>>;
};

export type WizardTurn = {
  session_id: string;
  state: string;
  message: string;
  awaiting?: string | null;
  done?: boolean;
  domain?: string | null;
  designer?: {
    model?: string;
    tier?: string;
    est_cost_usd?: number;
    routine_model?: string;
  } | null;
  proposal?: {
    domain?: string;
    title?: string;
    description?: string;
    interpretation?: string;
    objects?: WizardObject[];
    example_count?: number;
    archetype?: string;
    design_mode?: string;
  } | null;
  questions?: Array<string | { text?: string; prompt?: string }>;
  acceptance?: WizardAcceptance | null;
  dry_run?: WizardAcceptance | null;
  failures?: Array<Record<string, unknown>>;
  pack?: { name?: string; version?: string; path?: string; title?: string } | null;
  diff?: Record<string, unknown> | null;
  shortlist?: string[] | null;
  needs_repair?: boolean;
  design_mode?: string;
  neighborhood?: WizardNeighborhood | null;
  schema_preview?: Record<string, unknown> | null;
  simple_log?: boolean;
};

export type WizardNeighborhoodCard = {
  id: string;
  kind?: string;
  title: string;
  pitch?: string;
  aliases?: string[];
  why?: string;
  jobs?: string[];
  provenance?: "world" | "foundry" | "both" | string;
  world_analogs?: Array<{ name: string; one_liner: string }>;
  analog_pack?: string | null;
  example?: string;
  highlighted?: boolean;
};

export type WizardNeighborhood = {
  cursor?: string | null;
  breadcrumb?: Array<{ id: string; title: string; kind?: string }>;
  refine?: WizardNeighborhoodCard[];
  expand?: WizardNeighborhoodCard[];
  ideas?: WizardNeighborhoodCard[];
  simple_log?: boolean;
  unindexed?: boolean;
};
