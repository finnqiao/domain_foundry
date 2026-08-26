-- generated from FoundrySpec 1.0; do not edit in place
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS lifting_log__exercise (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    exercise_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('squat', 'hinge', 'press', 'pull', 'carry', 'accessory')),
    unit TEXT NOT NULL CHECK (unit IN ('kg', 'lb')),
    is_main_lift INTEGER CHECK (is_main_lift IN (0, 1)),
    bar_weight_kg REAL,
    cues TEXT,
    CONSTRAINT uq_exercise_identity UNIQUE (exercise_id),
    CONSTRAINT unique_movement_name UNIQUE (name)
);
CREATE INDEX IF NOT EXISTS ix_lifting_log__exercise_captured_at ON lifting_log__exercise(captured_at);

CREATE TABLE IF NOT EXISTS lifting_log__program (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    program_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('planned', 'running', 'deloading', 'completed', 'abandoned')),
    days_per_week INTEGER,
    started_on TEXT,
    progression_rule TEXT,
    deload_rule TEXT,
    CONSTRAINT uq_program_identity UNIQUE (program_id)
);
CREATE INDEX IF NOT EXISTS ix_lifting_log__program_captured_at ON lifting_log__program(captured_at);

CREATE TABLE IF NOT EXISTS lifting_log__prescription (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    prescription_id TEXT NOT NULL,
    program_id TEXT NOT NULL,
    exercise_id TEXT NOT NULL,
    day_label TEXT NOT NULL,
    scheme TEXT NOT NULL,
    target_load_kg REAL,
    load_step_kg REAL,
    order_index INTEGER,
    CONSTRAINT uq_prescription_identity UNIQUE (prescription_id),
    CONSTRAINT block_prescriptions FOREIGN KEY (program_id) REFERENCES lifting_log__program(program_id) ON DELETE CASCADE,
    CONSTRAINT prescribed_movement FOREIGN KEY (exercise_id) REFERENCES lifting_log__exercise(exercise_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_lifting_log__prescription_captured_at ON lifting_log__prescription(captured_at);

CREATE TABLE IF NOT EXISTS lifting_log__session (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    session_id TEXT NOT NULL,
    program_id TEXT NOT NULL,
    trained_at TEXT NOT NULL,
    day_label TEXT,
    bodyweight_kg REAL,
    notes TEXT,
    duration_min REAL,
    CONSTRAINT uq_session_identity UNIQUE (session_id),
    CONSTRAINT sane_bodyweight CHECK (bodyweight_kg > 20 AND bodyweight_kg < 300),
    CONSTRAINT block_sessions FOREIGN KEY (program_id) REFERENCES lifting_log__program(program_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_lifting_log__session_captured_at ON lifting_log__session(captured_at);

CREATE TABLE IF NOT EXISTS lifting_log__set_entry (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    set_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    exercise_id TEXT NOT NULL,
    scheme TEXT NOT NULL,
    sets INTEGER NOT NULL,
    reps INTEGER NOT NULL,
    load_kg REAL NOT NULL,
    rpe REAL,
    is_top_set INTEGER CHECK (is_top_set IN (0, 1)),
    is_pr INTEGER CHECK (is_pr IN (0, 1)),
    effort_note TEXT,
    order_index INTEGER,
    CONSTRAINT uq_set_entry_identity UNIQUE (set_id),
    CONSTRAINT sane_load CHECK (load_kg > 0 AND load_kg < 500),
    CONSTRAINT rpe_scale CHECK (rpe >= 1 AND rpe <= 10),
    CONSTRAINT real_scheme CHECK (sets > 0 AND reps > 0),
    CONSTRAINT session_sets FOREIGN KEY (session_id) REFERENCES lifting_log__session(session_id) ON DELETE CASCADE,
    CONSTRAINT set_movement FOREIGN KEY (exercise_id) REFERENCES lifting_log__exercise(exercise_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_lifting_log__set_entry_captured_at ON lifting_log__set_entry(captured_at);

CREATE INDEX IF NOT EXISTS session_day ON lifting_log__session(program_id, trained_at);
CREATE INDEX IF NOT EXISTS program_day_plan ON lifting_log__prescription(program_id, day_label, order_index);
CREATE INDEX IF NOT EXISTS lift_history ON lifting_log__set_entry(exercise_id, session_id);
CREATE INDEX IF NOT EXISTS pr_board ON lifting_log__set_entry(exercise_id, reps, load_kg);
