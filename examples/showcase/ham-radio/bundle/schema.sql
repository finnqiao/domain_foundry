-- generated from FoundrySpec 1.0; do not edit in place
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS ham_radio__station_profile (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    station_id TEXT NOT NULL,
    name TEXT NOT NULL,
    my_callsign TEXT NOT NULL,
    my_grid TEXT,
    rig TEXT NOT NULL,
    antenna TEXT NOT NULL,
    power_watts REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'retired')),
    CONSTRAINT uq_station_profile_identity UNIQUE (station_id),
    CONSTRAINT legal_power CHECK (power_watts > 0 AND power_watts <= 1500)
);
CREATE INDEX IF NOT EXISTS ix_ham_radio__station_profile_captured_at ON ham_radio__station_profile(captured_at);

CREATE TABLE IF NOT EXISTS ham_radio__dxcc_entity (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    entity_id TEXT NOT NULL,
    name TEXT NOT NULL,
    continent TEXT NOT NULL,
    prefix TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('current', 'deleted')),
    CONSTRAINT uq_dxcc_entity_identity UNIQUE (entity_id)
);
CREATE INDEX IF NOT EXISTS ix_ham_radio__dxcc_entity_captured_at ON ham_radio__dxcc_entity(captured_at);

CREATE TABLE IF NOT EXISTS ham_radio__qso (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    qso_id TEXT NOT NULL,
    station_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    callsign TEXT NOT NULL,
    band TEXT NOT NULL CHECK (band IN ('160m', '80m', '40m', '30m', '20m', '17m', '15m', '12m', '10m', '6m', '2m', '70cm')),
    mode TEXT NOT NULL CHECK (mode IN ('CW', 'SSB', 'FT8', 'FT4', 'RTTY', 'AM', 'FM')),
    frequency_mhz REAL NOT NULL,
    qso_at TEXT NOT NULL,
    rst_sent TEXT NOT NULL,
    rst_rcvd TEXT NOT NULL,
    grid_square TEXT,
    notes TEXT,
    CONSTRAINT uq_qso_identity UNIQUE (qso_id),
    CONSTRAINT sane_frequency CHECK (frequency_mhz > 0 AND frequency_mhz < 300),
    CONSTRAINT qso_station FOREIGN KEY (station_id) REFERENCES ham_radio__station_profile(station_id) ON DELETE RESTRICT,
    CONSTRAINT qso_entity FOREIGN KEY (entity_id) REFERENCES ham_radio__dxcc_entity(entity_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_ham_radio__qso_captured_at ON ham_radio__qso(captured_at);

CREATE TABLE IF NOT EXISTS ham_radio__qsl_record (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    qsl_id TEXT NOT NULL,
    qso_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('requested', 'sent', 'confirmed')),
    route TEXT NOT NULL CHECK (route IN ('bureau', 'direct', 'lotw', 'eqsl')),
    confirmed_at TEXT,
    CONSTRAINT uq_qsl_record_identity UNIQUE (qsl_id),
    CONSTRAINT qsl_trail FOREIGN KEY (qso_id) REFERENCES ham_radio__qso(qso_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_ham_radio__qsl_record_captured_at ON ham_radio__qsl_record(captured_at);

CREATE INDEX IF NOT EXISTS log_recency ON ham_radio__qso(band, mode, qso_at);
CREATE INDEX IF NOT EXISTS entity_progress ON ham_radio__qso(entity_id, qso_at);
CREATE INDEX IF NOT EXISTS activity_clock ON ham_radio__qso(band, qso_at);
