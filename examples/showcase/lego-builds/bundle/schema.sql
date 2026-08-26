-- generated from FoundrySpec 1.0; do not edit in place
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS lego_builds__lego_set (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    set_num TEXT NOT NULL,
    name TEXT NOT NULL,
    theme TEXT NOT NULL,
    piece_count INTEGER NOT NULL,
    minifig_count INTEGER NOT NULL,
    year_released INTEGER,
    availability TEXT NOT NULL CHECK (availability IN ('current', 'retired')),
    CONSTRAINT uq_lego_set_identity UNIQUE (set_num),
    CONSTRAINT real_piece_count CHECK (piece_count > 0 AND minifig_count >= 0)
);
CREATE INDEX IF NOT EXISTS ix_lego_builds__lego_set_captured_at ON lego_builds__lego_set(captured_at);

CREATE TABLE IF NOT EXISTS lego_builds__build_project (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    project_id TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('official_set', 'moc')),
    set_num TEXT,
    title TEXT NOT NULL,
    designer TEXT,
    piece_count_claimed INTEGER,
    footprint_studs INTEGER,
    status TEXT NOT NULL CHECK (status IN ('sealed', 'wip', 'built', 'displayed', 'parted_out')),
    storage_slot_id TEXT,
    instructions_location TEXT,
    bags_total INTEGER,
    started_at TEXT,
    completed_at TEXT,
    notes TEXT,
    CONSTRAINT uq_build_project_identity UNIQUE (project_id),
    CONSTRAINT project_source_set FOREIGN KEY (set_num) REFERENCES lego_builds__lego_set(set_num) ON DELETE RESTRICT,
    CONSTRAINT project_storage FOREIGN KEY (storage_slot_id) REFERENCES lego_builds__storage_slot(slot_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_lego_builds__build_project_captured_at ON lego_builds__build_project(captured_at);

CREATE TABLE IF NOT EXISTS lego_builds__build_session (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    session_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    worked_at TEXT NOT NULL,
    duration_min INTEGER,
    bags_completed TEXT,
    step_reached INTEGER,
    pieces_placed INTEGER,
    notes TEXT,
    CONSTRAINT uq_build_session_identity UNIQUE (session_id),
    CONSTRAINT real_sitting CHECK (duration_min > 0 AND step_reached >= 0),
    CONSTRAINT project_sittings FOREIGN KEY (project_id) REFERENCES lego_builds__build_project(project_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_lego_builds__build_session_captured_at ON lego_builds__build_session(captured_at);

CREATE TABLE IF NOT EXISTS lego_builds__part_shortage (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    shortage_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    part_num TEXT NOT NULL,
    part_name TEXT,
    element_kind TEXT NOT NULL CHECK (element_kind IN ('tile', 'plate', 'brick', 'slope', 'technic', 'minifig_part', 'other')),
    color_name TEXT,
    quantity_missing INTEGER NOT NULL,
    noticed_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'ordered', 'received', 'substituted', 'waived')),
    notes TEXT,
    CONSTRAINT uq_part_shortage_identity UNIQUE (shortage_id),
    CONSTRAINT short_by_something CHECK (quantity_missing > 0 AND quantity_missing <= 9999),
    CONSTRAINT project_shortages FOREIGN KEY (project_id) REFERENCES lego_builds__build_project(project_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_lego_builds__part_shortage_captured_at ON lego_builds__part_shortage(captured_at);

CREATE TABLE IF NOT EXISTS lego_builds__storage_slot (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    slot_id TEXT NOT NULL,
    label TEXT NOT NULL,
    slot_kind TEXT NOT NULL CHECK (slot_kind IN ('display_shelf', 'parts_bin', 'sealed_stack', 'instruction_binder')),
    room TEXT,
    capacity_note TEXT,
    CONSTRAINT uq_storage_slot_identity UNIQUE (slot_id),
    CONSTRAINT unique_slot_label UNIQUE (label)
);
CREATE INDEX IF NOT EXISTS ix_lego_builds__storage_slot_captured_at ON lego_builds__storage_slot(captured_at);

CREATE INDEX IF NOT EXISTS wip_bench ON lego_builds__build_project(status, started_at);
CREATE INDEX IF NOT EXISTS project_sitting_order ON lego_builds__build_session(project_id, worked_at);
CREATE INDEX IF NOT EXISTS open_shortages ON lego_builds__part_shortage(status, part_num);
CREATE INDEX IF NOT EXISTS shelf_by_theme ON lego_builds__lego_set(theme, year_released);
