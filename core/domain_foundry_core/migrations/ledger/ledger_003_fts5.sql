-- ledger_003_fts5.sql
-- Phase 2 (G8): unified FTS5 substrate over entry raw text + canonical text.
-- Additive only. Legacy entry_fts remains; search_document/search_fts are the
-- HarnessAPI.search() + query(q=...) source of truth, synced by triggers.

PRAGMA foreign_keys = ON;

-- Denormalized blob written by apply; triggers mirror it into search_document.
ALTER TABLE canonical_object ADD COLUMN searchable_text TEXT;

CREATE TABLE IF NOT EXISTS search_document (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('entry', 'canonical')),
    ref_id          TEXT NOT NULL,
    domain          TEXT,
    object_type     TEXT,
    raw_text        TEXT,
    canonical_text  TEXT,
    updated_at      TEXT NOT NULL,
    UNIQUE (kind, ref_id)
);
CREATE INDEX IF NOT EXISTS search_document_domain_idx
    ON search_document(domain, object_type);
CREATE INDEX IF NOT EXISTS search_document_ref_idx
    ON search_document(ref_id);

CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
    raw_text,
    canonical_text,
    domain UNINDEXED,
    object_type UNINDEXED,
    content='search_document',
    content_rowid='id'
);

-- ---------------------------------------------------------------------------
-- search_document ↔ search_fts content sync (idempotent delete+insert pattern)
-- ---------------------------------------------------------------------------
CREATE TRIGGER IF NOT EXISTS search_document_ai
AFTER INSERT ON search_document BEGIN
    INSERT INTO search_fts(rowid, raw_text, canonical_text, domain, object_type)
    VALUES (new.id, new.raw_text, new.canonical_text, new.domain, new.object_type);
END;

CREATE TRIGGER IF NOT EXISTS search_document_ad
AFTER DELETE ON search_document BEGIN
    INSERT INTO search_fts(search_fts, rowid, raw_text, canonical_text, domain, object_type)
    VALUES ('delete', old.id, old.raw_text, old.canonical_text, old.domain, old.object_type);
END;

CREATE TRIGGER IF NOT EXISTS search_document_au
AFTER UPDATE ON search_document BEGIN
    INSERT INTO search_fts(search_fts, rowid, raw_text, canonical_text, domain, object_type)
    VALUES ('delete', old.id, old.raw_text, old.canonical_text, old.domain, old.object_type);
    INSERT INTO search_fts(rowid, raw_text, canonical_text, domain, object_type)
    VALUES (new.id, new.raw_text, new.canonical_text, new.domain, new.object_type);
END;

-- ---------------------------------------------------------------------------
-- Entry raw text: mirror capture_event.raw_text + entry.summary into the index
-- ---------------------------------------------------------------------------
CREATE TRIGGER IF NOT EXISTS search_entry_ai
AFTER INSERT ON entry BEGIN
    INSERT INTO search_document (
        kind, ref_id, domain, object_type, raw_text, canonical_text, updated_at
    )
    SELECT
        'entry', new.id, new.domain, new.object_type, c.raw_text, new.summary, new.updated_at
    FROM capture_event c
    WHERE c.id = new.capture_event_id
    ON CONFLICT(kind, ref_id) DO UPDATE SET
        domain = excluded.domain,
        object_type = excluded.object_type,
        raw_text = excluded.raw_text,
        canonical_text = excluded.canonical_text,
        updated_at = excluded.updated_at;
END;

CREATE TRIGGER IF NOT EXISTS search_entry_au
AFTER UPDATE OF domain, object_type, summary, updated_at ON entry BEGIN
    INSERT INTO search_document (
        kind, ref_id, domain, object_type, raw_text, canonical_text, updated_at
    )
    SELECT
        'entry', new.id, new.domain, new.object_type, c.raw_text, new.summary, new.updated_at
    FROM capture_event c
    WHERE c.id = new.capture_event_id
    ON CONFLICT(kind, ref_id) DO UPDATE SET
        domain = excluded.domain,
        object_type = excluded.object_type,
        raw_text = excluded.raw_text,
        canonical_text = excluded.canonical_text,
        updated_at = excluded.updated_at;
END;

CREATE TRIGGER IF NOT EXISTS search_entry_ad
AFTER DELETE ON entry BEGIN
    DELETE FROM search_document WHERE kind = 'entry' AND ref_id = old.id;
END;

-- ---------------------------------------------------------------------------
-- Canonical text: mirror canonical_object.searchable_text into the index
-- ---------------------------------------------------------------------------
CREATE TRIGGER IF NOT EXISTS search_canonical_ai
AFTER INSERT ON canonical_object BEGIN
    INSERT INTO search_document (
        kind, ref_id, domain, object_type, raw_text, canonical_text, updated_at
    ) VALUES (
        'canonical', new.uid, new.domain, new.object_type, NULL,
        new.searchable_text, new.updated_at
    )
    ON CONFLICT(kind, ref_id) DO UPDATE SET
        domain = excluded.domain,
        object_type = excluded.object_type,
        canonical_text = excluded.canonical_text,
        updated_at = excluded.updated_at;
END;

CREATE TRIGGER IF NOT EXISTS search_canonical_au
AFTER UPDATE OF searchable_text, domain, object_type, status, updated_at
ON canonical_object BEGIN
    INSERT INTO search_document (
        kind, ref_id, domain, object_type, raw_text, canonical_text, updated_at
    ) VALUES (
        'canonical', new.uid, new.domain, new.object_type, NULL,
        CASE WHEN new.status = 'tombstoned' THEN NULL ELSE new.searchable_text END,
        new.updated_at
    )
    ON CONFLICT(kind, ref_id) DO UPDATE SET
        domain = excluded.domain,
        object_type = excluded.object_type,
        canonical_text = excluded.canonical_text,
        updated_at = excluded.updated_at;
END;

CREATE TRIGGER IF NOT EXISTS search_canonical_ad
AFTER DELETE ON canonical_object BEGIN
    DELETE FROM search_document WHERE kind = 'canonical' AND ref_id = old.uid;
END;

-- Backfill from existing rows (fresh installs are empty; upgrades get coverage).
INSERT INTO search_document (
    kind, ref_id, domain, object_type, raw_text, canonical_text, updated_at
)
SELECT
    'entry', e.id, e.domain, e.object_type, c.raw_text, e.summary, e.updated_at
FROM entry e
JOIN capture_event c ON c.id = e.capture_event_id
WHERE NOT EXISTS (
    SELECT 1 FROM search_document sd
    WHERE sd.kind = 'entry' AND sd.ref_id = e.id
);

INSERT INTO search_document (
    kind, ref_id, domain, object_type, raw_text, canonical_text, updated_at
)
SELECT
    'canonical', co.uid, co.domain, co.object_type, NULL, co.searchable_text, co.updated_at
FROM canonical_object co
WHERE NOT EXISTS (
    SELECT 1 FROM search_document sd
    WHERE sd.kind = 'canonical' AND sd.ref_id = co.uid
);
