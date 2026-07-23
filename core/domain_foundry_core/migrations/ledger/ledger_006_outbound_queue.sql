-- ledger_006_outbound_queue.sql
-- Durable Expert → channel outbound multiplex (mesh P1 remainder / P2 hook).
-- See docs/PER_DOMAIN_AGENT_MESH_2026-07-20.md §7; plan Phase 3–4.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Outbound delivery queue (Experts/Concierge enqueue; gateway polls + retries)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outbound_queue (
    id                  TEXT PRIMARY KEY,              -- ULID
    origin_domain       TEXT NOT NULL,                 -- japanese | food | ...
    payload_json        TEXT NOT NULL,                 -- text/channel/destination + extras
    status              TEXT NOT NULL DEFAULT 'pending',
        -- pending | delivering | delivered | dead
    attempts            INTEGER NOT NULL DEFAULT 0,
    next_attempt_at     TEXT NOT NULL,                 -- UTC ISO-8601; claim when <= now
    last_error          TEXT,
    created_at          TEXT NOT NULL,
    claimed_at          TEXT,
    delivered_at        TEXT
);
CREATE INDEX IF NOT EXISTS outbound_queue_ready_idx
    ON outbound_queue(status, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS outbound_queue_domain_idx
    ON outbound_queue(origin_domain, status, created_at);
