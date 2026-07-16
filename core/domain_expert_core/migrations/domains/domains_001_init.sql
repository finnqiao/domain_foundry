-- domains_001_init.sql
-- Pack-owned tables are created by the schema compiler (P2).
-- This migration only ensures FK pragma and a marker table.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS domains_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO domains_meta (key, value)
VALUES ('initialized', '1');
