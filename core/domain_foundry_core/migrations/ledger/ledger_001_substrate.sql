-- ledger_001_substrate.sql
-- Capture-first substrate for domain_expert (clean re-type; additive-only).
-- See docs/adr/ADR-002-two-database-layout.md and plan §4.3.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Raw ingress
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS capture_event (
    id                  TEXT PRIMARY KEY,              -- ULID
    channel             TEXT NOT NULL,                 -- cli | web | telegram | ...
    source_ref          TEXT,                          -- idempotency key (channel-scoped)
    actor               TEXT,
    raw_text            TEXT,
    raw_payload_json    TEXT,
    attachments_json    TEXT,
    content_hash        TEXT,
    captured_at         TEXT NOT NULL,                 -- UTC ISO-8601
    created_at          TEXT NOT NULL,
    UNIQUE (channel, source_ref)
);
CREATE INDEX IF NOT EXISTS capture_event_captured_at_idx
    ON capture_event(captured_at);

-- ---------------------------------------------------------------------------
-- User-facing capture unit
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entry (
    id                  TEXT PRIMARY KEY,              -- ULID
    capture_event_id    TEXT NOT NULL REFERENCES capture_event(id),
    status              TEXT NOT NULL DEFAULT 'ledger_only',
        -- applied | review | ledger_only | unfiled
    domain              TEXT,
    object_type         TEXT,
    operation           TEXT,
    routing_confidence  REAL,
    fallback_tier       TEXT,                          -- pack_fallback | unfiled_card | ledger_only
    summary             TEXT,
    privacy_level       TEXT NOT NULL DEFAULT 'normal',
    tags_json           TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS entry_status_idx ON entry(status);
CREATE INDEX IF NOT EXISTS entry_domain_idx ON entry(domain, object_type);
CREATE INDEX IF NOT EXISTS entry_capture_idx ON entry(capture_event_id);
CREATE INDEX IF NOT EXISTS entry_created_at_idx ON entry(created_at);

CREATE TABLE IF NOT EXISTS source_link (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type     TEXT NOT NULL,                     -- capture_event | message | import
    source_id       TEXT NOT NULL,
    target_type     TEXT NOT NULL,                     -- entry | canonical_object
    target_id       TEXT NOT NULL,
    relationship    TEXT NOT NULL DEFAULT 'created_from',
    confidence      REAL DEFAULT 1.0,
    created_at      TEXT NOT NULL,
    UNIQUE (source_type, source_id, target_type, target_id, relationship)
);
CREATE INDEX IF NOT EXISTS source_link_source_idx ON source_link(source_type, source_id);
CREATE INDEX IF NOT EXISTS source_link_target_idx ON source_link(target_type, target_id);

-- ---------------------------------------------------------------------------
-- Interpretation & change proposals
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interpretation (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id              TEXT NOT NULL REFERENCES entry(id),
    version               INTEGER NOT NULL DEFAULT 1,
    interpreter           TEXT NOT NULL,               -- rules | llm:<provider>
    payload_json          TEXT NOT NULL,
    confidence            REAL NOT NULL DEFAULT 1.0,
    status                TEXT NOT NULL DEFAULT 'proposed',
        -- proposed | applied | superseded | rejected
    superseded_by         INTEGER REFERENCES interpretation(id),
    input_tokens          INTEGER DEFAULT 0,
    output_tokens         INTEGER DEFAULT 0,
    token_cost_usd        REAL,
    created_at            TEXT NOT NULL,
    UNIQUE (entry_id, version)
);
CREATE INDEX IF NOT EXISTS interpretation_entry_idx ON interpretation(entry_id, version);

CREATE TABLE IF NOT EXISTS change_request (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id            TEXT NOT NULL REFERENCES entry(id),
    interpretation_id   INTEGER REFERENCES interpretation(id),
    domain              TEXT NOT NULL,
    object_type         TEXT,
    operation           TEXT NOT NULL,                 -- create | update | correct | merge | delete
    object_uid          TEXT,
    payload_json        TEXT NOT NULL,
    confidence          REAL DEFAULT 1.0,
    channel             TEXT,
    client_ref          TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
        -- pending | approved | applied | denied | superseded | failed
    result_json         TEXT,
    error               TEXT,
    created_at          TEXT NOT NULL,
    applied_at          TEXT
);
CREATE INDEX IF NOT EXISTS change_request_entry_idx ON change_request(entry_id);
CREATE INDEX IF NOT EXISTS change_request_status_idx ON change_request(status);
CREATE INDEX IF NOT EXISTS change_request_domain_idx ON change_request(domain, operation);
CREATE UNIQUE INDEX IF NOT EXISTS change_request_client_ref_idx
    ON change_request(channel, client_ref)
    WHERE client_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS approval_queue (
    id                  TEXT PRIMARY KEY,              -- ULID
    change_request_id   INTEGER NOT NULL REFERENCES change_request(id),
    decision_status     TEXT NOT NULL DEFAULT 'pending',
        -- pending | approved | denied | expired
    application_status  TEXT NOT NULL DEFAULT 'not_started',
        -- not_started | applied | failed | skipped
    domain              TEXT,
    summary             TEXT,
    diff_json           TEXT,
    created_at          TEXT NOT NULL,
    expires_at          TEXT,
    resolved_at         TEXT,
    resolver            TEXT,
    resolver_note       TEXT,
    execution_receipt_json TEXT
);
CREATE INDEX IF NOT EXISTS approval_decision_idx ON approval_queue(decision_status);
CREATE INDEX IF NOT EXISTS approval_application_idx ON approval_queue(application_status);

-- ---------------------------------------------------------------------------
-- Canonical journal
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_object (
    uid             TEXT PRIMARY KEY,                  -- <pack>:<object_type>:<ulid>
    domain          TEXT NOT NULL,
    object_type     TEXT NOT NULL,
    store           TEXT NOT NULL DEFAULT 'domains',
    table_name      TEXT NOT NULL,
    row_id          INTEGER,
    natural_key     TEXT,
    status          TEXT NOT NULL DEFAULT 'active',    -- active | tombstoned | merged
    merged_into_uid TEXT REFERENCES canonical_object(uid),
    schema_version  INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS canonical_object_domain_idx
    ON canonical_object(domain, object_type, status);
CREATE UNIQUE INDEX IF NOT EXISTS canonical_object_natural_idx
    ON canonical_object(domain, object_type, natural_key)
    WHERE natural_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS object_revision (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid          TEXT NOT NULL REFERENCES canonical_object(uid),
    change_request_id   INTEGER REFERENCES change_request(id),
    revision            INTEGER NOT NULL,
    changed_fields_json TEXT NOT NULL,
    actor               TEXT NOT NULL,
    actor_channel       TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE (object_uid, revision)
);
CREATE INDEX IF NOT EXISTS object_revision_uid_idx ON object_revision(object_uid, revision);

CREATE TABLE IF NOT EXISTS correction_event (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id                    TEXT REFERENCES entry(id),
    target_kind                 TEXT NOT NULL,         -- entry | object | interpretation
    target_id                   TEXT NOT NULL,
    reason_code                 TEXT NOT NULL,
    wrong_json                  TEXT,
    right_json                  TEXT,
    applied_change_request_id   INTEGER REFERENCES change_request(id),
    created_at                  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS correction_event_entry_idx ON correction_event(entry_id);
CREATE INDEX IF NOT EXISTS correction_event_target_idx ON correction_event(target_kind, target_id);

-- ---------------------------------------------------------------------------
-- Never-drop: unfiled card storage
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS unfiled_card (
    id                  TEXT PRIMARY KEY,
    entry_id            TEXT NOT NULL REFERENCES entry(id),
    capture_event_id    TEXT NOT NULL REFERENCES capture_event(id),
    title               TEXT NOT NULL,
    data_json           TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'open',  -- open | filed | dismissed
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS unfiled_card_status_idx ON unfiled_card(status);

-- ---------------------------------------------------------------------------
-- Projections
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projection_outbox (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    adapter             TEXT NOT NULL,                 -- markdown | app_feed
    object_key          TEXT NOT NULL,
    watermark           TEXT,
    reason              TEXT,
    change_request_id   INTEGER REFERENCES change_request(id),
    status              TEXT NOT NULL DEFAULT 'pending',
        -- pending | draining | done | failed
    attempts            INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    drained_at          TEXT
);
CREATE INDEX IF NOT EXISTS projection_outbox_pending_idx
    ON projection_outbox(status, adapter, id);

CREATE TABLE IF NOT EXISTS projection_watermark (
    adapter     TEXT NOT NULL,
    object_key  TEXT NOT NULL,
    watermark   TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (adapter, object_key)
);

-- ---------------------------------------------------------------------------
-- Policy, schema registry, evals, cost
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS apply_policy (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    domain               TEXT NOT NULL,
    operation            TEXT NOT NULL DEFAULT '*',
    object_type          TEXT NOT NULL DEFAULT '*',
    channel              TEXT NOT NULL DEFAULT '*',
    min_confidence       REAL NOT NULL DEFAULT 0.8,
    condition_json       TEXT,
    action               TEXT NOT NULL DEFAULT 'auto_apply',
        -- auto_apply | review | confirm | reject
    priority             INTEGER NOT NULL DEFAULT 100,
    source               TEXT NOT NULL DEFAULT 'pack',  -- pack | user
    UNIQUE (domain, operation, object_type, channel, source)
);
CREATE INDEX IF NOT EXISTS apply_policy_priority_idx ON apply_policy(domain, priority, action);

CREATE TABLE IF NOT EXISTS schema_registry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain          TEXT NOT NULL,
    object_type     TEXT NOT NULL,
    schema_version  INTEGER NOT NULL DEFAULT 1,
    pack_version    TEXT,
    field_contract_json TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    migration_notes TEXT,
    UNIQUE (domain, object_type, schema_version)
);
CREATE INDEX IF NOT EXISTS schema_registry_domain_idx
    ON schema_registry(domain, object_type, active);

CREATE TABLE IF NOT EXISTS eval_case (
    id                      TEXT PRIMARY KEY,
    source                  TEXT NOT NULL,             -- pack_fixture | correction | curated
    raw_text                TEXT NOT NULL,
    context_json            TEXT NOT NULL,
    expected_json           TEXT NOT NULL,
    provenance_json         TEXT,
    correction_event_id     INTEGER REFERENCES correction_event(id),
    created_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS eval_case_source_idx ON eval_case(source);

CREATE TABLE IF NOT EXISTS cost_ledger (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    day             TEXT NOT NULL,                     -- YYYY-MM-DD UTC
    provider        TEXT NOT NULL,
    model           TEXT,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0,
    entry_id        TEXT REFERENCES entry(id),
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cost_ledger_day_idx ON cost_ledger(day);

-- FTS for entry search (P1 query path)
CREATE VIRTUAL TABLE IF NOT EXISTS entry_fts USING fts5(
    entry_id UNINDEXED,
    raw_text,
    summary,
    domain
);
