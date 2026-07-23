-- ledger_007_mesh_sessions.sql
-- Mesh P2: interactive sessions + schedule bookkeeping.
-- outbound_queue already landed in ledger_006 (Phase 3).
-- See docs/PER_DOMAIN_AGENT_MESH_2026-07-20.md §5 / §7.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Active multi-turn sessions (quiz, wizard-style flows, …)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS domain_session (
    id                  TEXT PRIMARY KEY,              -- ULID
    domain              TEXT NOT NULL,
    user_id             TEXT NOT NULL DEFAULT 'default',
    session_type        TEXT NOT NULL,                 -- quiz | …
    state_json          TEXT NOT NULL DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'active',
        -- active | paused | completed | cancelled
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS domain_session_active_idx
    ON domain_session(domain, user_id, status, updated_at);
CREATE INDEX IF NOT EXISTS domain_session_type_idx
    ON domain_session(domain, session_type, status);

-- ---------------------------------------------------------------------------
-- Scheduler bookkeeping — idempotent next-due / last-fired per schedule
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schedule_run (
    id                  TEXT PRIMARY KEY,              -- ULID
    domain              TEXT NOT NULL,
    schedule_id         TEXT NOT NULL,
    last_fired_at       TEXT,
    next_due_at         TEXT,
    fire_count          INTEGER NOT NULL DEFAULT 0,
    last_result_json    TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (domain, schedule_id)
);
CREATE INDEX IF NOT EXISTS schedule_run_due_idx
    ON schedule_run(next_due_at, domain);
