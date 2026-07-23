-- ledger_005_mesh_inbox.sql
-- Mesh P1 transport tables: journal-first ingress + per-domain durable queues.
-- See docs/PER_DOMAIN_AGENT_MESH_2026-07-20.md §7.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Transport-level capture-first journal (Concierge writes before routing)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inbox_journal (
    id                  TEXT PRIMARY KEY,              -- ULID
    channel             TEXT NOT NULL,                 -- telegram | whatsapp | cli | ...
    source_ref          TEXT,                          -- channel-scoped idempotency key
    actor               TEXT,
    raw_text            TEXT NOT NULL,
    payload_json        TEXT,                          -- optional channel envelope
    status              TEXT NOT NULL DEFAULT 'pending',
        -- pending | routed | failed
    routed_domain       TEXT,
    domain_inbox_id     TEXT,                          -- set once enqueued
    error               TEXT,
    journaled_at        TEXT NOT NULL,                 -- UTC ISO-8601
    routed_at           TEXT,
    UNIQUE (channel, source_ref)
);
CREATE INDEX IF NOT EXISTS inbox_journal_status_idx
    ON inbox_journal(status, journaled_at);
CREATE INDEX IF NOT EXISTS inbox_journal_journaled_at_idx
    ON inbox_journal(journaled_at);

-- ---------------------------------------------------------------------------
-- Per-domain durable work queue (Experts dequeue serially within a domain)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS domain_inbox (
    id                  TEXT PRIMARY KEY,              -- ULID (msg_id)
    domain              TEXT NOT NULL,
    journal_id          TEXT NOT NULL REFERENCES inbox_journal(id),
    payload_json        TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
        -- pending | processing | done | failed | dead
    enqueued_at         TEXT NOT NULL,
    claimed_at          TEXT,
    acked_at            TEXT,
    error               TEXT,
    reply_json          TEXT,
    UNIQUE (journal_id, domain)
);
CREATE INDEX IF NOT EXISTS domain_inbox_domain_status_idx
    ON domain_inbox(domain, status, enqueued_at);
CREATE INDEX IF NOT EXISTS domain_inbox_journal_idx
    ON domain_inbox(journal_id);
