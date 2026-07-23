-- ledger_007_domain_session.sql
-- Mesh P3 Concierge UX: active multi-turn sessions for stickiness.
-- (outbound_queue already landed in ledger_006; sessions are additive here.)
-- See docs/PER_DOMAIN_AGENT_MESH_2026-07-20.md §5.3.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Active multi-turn sessions (quiz, sticky focus, …)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS domain_session (
    id                  TEXT PRIMARY KEY,              -- ULID
    domain              TEXT NOT NULL,
    user_id             TEXT NOT NULL DEFAULT 'default',
    session_type        TEXT NOT NULL,                 -- quiz | sticky | …
    state_json          TEXT NOT NULL DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'active',
        -- active | paused | completed | cancelled
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS domain_session_active_idx
    ON domain_session(domain, user_id, status, updated_at);
CREATE INDEX IF NOT EXISTS domain_session_user_active_idx
    ON domain_session(user_id, status, updated_at);
CREATE INDEX IF NOT EXISTS domain_session_type_idx
    ON domain_session(domain, session_type, status);

-- ---------------------------------------------------------------------------
-- Concierge not_mine / routing bounce corrections (feeds eval bank)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS routing_correction (
    id                  TEXT PRIMARY KEY,              -- ULID
    journal_id          TEXT NOT NULL REFERENCES inbox_journal(id),
    bounced_domain      TEXT NOT NULL,
    routed_domain       TEXT NOT NULL,
    raw_text            TEXT NOT NULL,
    reason_code         TEXT NOT NULL DEFAULT 'not_mine',
    eval_case_id        TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS routing_correction_journal_idx
    ON routing_correction(journal_id);
CREATE INDEX IF NOT EXISTS routing_correction_created_idx
    ON routing_correction(created_at);
