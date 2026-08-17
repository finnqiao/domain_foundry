-- Slice 3: user-visible schedule pause/revoke state.
-- The existing schedule_run table remains an idempotency ledger; controls are
-- separate so pausing does not erase firing history or receipts.

CREATE TABLE IF NOT EXISTS schedule_control (
    domain      TEXT NOT NULL,
    schedule_id TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (domain, schedule_id),
    CHECK (status IN ('active', 'paused', 'revoked'))
);
