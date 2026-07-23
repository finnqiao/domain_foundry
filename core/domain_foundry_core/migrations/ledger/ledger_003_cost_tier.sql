-- ledger_003_cost_tier.sql
-- Per-tier cost metering for Phase 1 LLM guard (routine / sota).

PRAGMA foreign_keys = ON;

ALTER TABLE cost_ledger ADD COLUMN tier TEXT;

CREATE INDEX IF NOT EXISTS cost_ledger_day_tier_idx ON cost_ledger(day, tier);
