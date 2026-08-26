-- ledger_010_cost_entry_label.sql
-- Let cost_ledger.entry_id carry create-time spend that belongs to no entry.
--
-- ledger_001 declared `entry_id TEXT REFERENCES entry(id)`, which was right while
-- every metered call was caused by a capture. ADR-010's Foundry meter is not:
-- proposing and completing a specification is six sota calls made *before* the
-- pack exists, so there is no entry to point at and never will be. With foreign
-- keys ON (security/store.connect_rw sets them), every such row failed to insert
-- and the daily cost guard could not see the most expensive path in the product.
--
-- The column keeps its meaning for capture-caused rows and now also accepts a
-- create-time label such as `foundry:<session>:<stage>`. The constraint is
-- dropped rather than the label being smuggled into another column, because a
-- half-true foreign key is worse than an honest free-text attribution.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cost_ledger_v10 (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    day             TEXT NOT NULL,                     -- YYYY-MM-DD UTC
    provider        TEXT NOT NULL,
    model           TEXT,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0,
    -- An entry id when a capture caused the spend, or a create-time label.
    entry_id        TEXT,
    created_at      TEXT NOT NULL,
    tier            TEXT
);

INSERT INTO cost_ledger_v10 (
    id, day, provider, model, input_tokens, output_tokens,
    cost_usd, entry_id, created_at, tier
)
SELECT id, day, provider, model, input_tokens, output_tokens,
       cost_usd, entry_id, created_at, tier
FROM cost_ledger;

DROP TABLE cost_ledger;

ALTER TABLE cost_ledger_v10 RENAME TO cost_ledger;

CREATE INDEX IF NOT EXISTS cost_ledger_day_idx ON cost_ledger(day);
CREATE INDEX IF NOT EXISTS cost_ledger_day_tier_idx ON cost_ledger(day, tier);
