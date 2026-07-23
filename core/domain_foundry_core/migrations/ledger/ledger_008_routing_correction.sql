-- ledger_008_routing_correction.sql
-- Mesh P3 Concierge UX: sticky lookup index + not_mine bounce corrections.
-- domain_session + schedule_run already landed in ledger_007_mesh_sessions.
-- See docs/PER_DOMAIN_AGENT_MESH_2026-07-20.md §5.3.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Cross-domain sticky lookup (most recent active session per user)
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS domain_session_user_active_idx
    ON domain_session(user_id, status, updated_at);

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
