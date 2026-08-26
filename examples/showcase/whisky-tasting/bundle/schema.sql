-- generated from FoundrySpec 1.0; do not edit in place
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS whisky_tasting__distillery (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    distillery_id TEXT NOT NULL,
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    country TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'silent')),
    CONSTRAINT uq_distillery_identity UNIQUE (distillery_id)
);
CREATE INDEX IF NOT EXISTS ix_whisky_tasting__distillery_captured_at ON whisky_tasting__distillery(captured_at);

CREATE TABLE IF NOT EXISTS whisky_tasting__bottle (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    bottle_id TEXT NOT NULL,
    distillery_id TEXT NOT NULL,
    expression TEXT NOT NULL,
    age_years INTEGER,
    abv_pct REAL NOT NULL,
    cask_type TEXT,
    bottler TEXT NOT NULL CHECK (bottler IN ('official', 'independent')),
    peated INTEGER CHECK (peated IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('sealed', 'open', 'finished', 'archived')),
    fill_level_pct REAL,
    price_paid REAL,
    acquired_at TEXT,
    label_photo TEXT,
    CONSTRAINT uq_bottle_identity UNIQUE (bottle_id),
    CONSTRAINT sane_strength CHECK (abv_pct > 0 AND abv_pct <= 85),
    CONSTRAINT bottle_producer FOREIGN KEY (distillery_id) REFERENCES whisky_tasting__distillery(distillery_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_whisky_tasting__bottle_captured_at ON whisky_tasting__bottle(captured_at);

CREATE TABLE IF NOT EXISTS whisky_tasting__dram (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    dram_id TEXT NOT NULL,
    bottle_id TEXT NOT NULL,
    poured_at TEXT NOT NULL,
    serving TEXT NOT NULL CHECK (serving IN ('neat', 'drop_of_water', 'rocks', 'highball')),
    nose TEXT,
    palate TEXT,
    finish TEXT,
    score INTEGER,
    context TEXT,
    CONSTRAINT uq_dram_identity UNIQUE (dram_id),
    CONSTRAINT scored_scale CHECK (score >= 0 AND score <= 100),
    CONSTRAINT bottle_drams FOREIGN KEY (bottle_id) REFERENCES whisky_tasting__bottle(bottle_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_whisky_tasting__dram_captured_at ON whisky_tasting__dram(captured_at);

CREATE TABLE IF NOT EXISTS whisky_tasting__flavor_note (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    note_id TEXT NOT NULL,
    dram_id TEXT NOT NULL,
    descriptor TEXT NOT NULL,
    axis TEXT NOT NULL CHECK (axis IN ('nose', 'palate', 'finish')),
    intensity INTEGER,
    CONSTRAINT uq_flavor_note_identity UNIQUE (note_id),
    CONSTRAINT dram_notes FOREIGN KEY (dram_id) REFERENCES whisky_tasting__dram(dram_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_whisky_tasting__flavor_note_captured_at ON whisky_tasting__flavor_note(captured_at);

CREATE INDEX IF NOT EXISTS bottle_story ON whisky_tasting__dram(bottle_id, poured_at);
CREATE INDEX IF NOT EXISTS palate_recurrence ON whisky_tasting__flavor_note(descriptor, axis);
CREATE INDEX IF NOT EXISTS open_shelf ON whisky_tasting__bottle(status, fill_level_pct);
