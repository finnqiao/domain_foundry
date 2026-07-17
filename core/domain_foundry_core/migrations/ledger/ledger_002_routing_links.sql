-- ledger_002_routing_links.sql
-- Cross-domain link records from L2 fan-out + rule demotion state.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS object_link (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    from_change_request_id INTEGER REFERENCES change_request(id),
    to_change_request_id   INTEGER REFERENCES change_request(id),
    from_domain         TEXT NOT NULL,
    to_domain           TEXT NOT NULL,
    relation            TEXT NOT NULL DEFAULT 'related',
    entry_id            TEXT REFERENCES entry(id),
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS object_link_entry_idx ON object_link(entry_id);
CREATE INDEX IF NOT EXISTS object_link_domains_idx ON object_link(from_domain, to_domain);

CREATE TABLE IF NOT EXISTS rule_demotion (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pack            TEXT NOT NULL,
    rule_index      INTEGER NOT NULL,
    pattern         TEXT NOT NULL,
    demotion_count  INTEGER NOT NULL DEFAULT 0,
    confidence_cap  REAL,
    updated_at      TEXT NOT NULL,
    UNIQUE (pack, rule_index)
);

CREATE TABLE IF NOT EXISTS pack_install (
    name            TEXT PRIMARY KEY,
    version         TEXT NOT NULL,
    path            TEXT NOT NULL,
    installed_at    TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1
);
