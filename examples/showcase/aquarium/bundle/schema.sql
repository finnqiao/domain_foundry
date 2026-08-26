-- generated from FoundrySpec 1.0; do not edit in place
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS aquarium_tank__tank (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    tank_id TEXT NOT NULL,
    name TEXT NOT NULL,
    volume_liters REAL NOT NULL,
    water_type TEXT NOT NULL CHECK (water_type IN ('freshwater', 'brackish', 'marine')),
    planted INTEGER CHECK (planted IN (0, 1)),
    started_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('cycling', 'cycled', 'established', 'rescaped', 'retired')),
    substrate TEXT,
    notes TEXT,
    CONSTRAINT uq_tank_identity UNIQUE (tank_id),
    CONSTRAINT positive_volume CHECK (volume_liters > 0)
);
CREATE INDEX IF NOT EXISTS ix_aquarium_tank__tank_captured_at ON aquarium_tank__tank(captured_at);

CREATE TABLE IF NOT EXISTS aquarium_tank__inhabitant (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    inhabitant_id TEXT NOT NULL,
    tank_id TEXT NOT NULL,
    common_name TEXT NOT NULL,
    scientific_name TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('fish', 'invertebrate', 'plant')),
    quantity INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    source TEXT,
    status TEXT NOT NULL CHECK (status IN ('alive', 'lost', 'rehomed')),
    temp_min_f REAL,
    temp_max_f REAL,
    ph_min REAL,
    ph_max REAL,
    min_group INTEGER,
    notes TEXT,
    CONSTRAINT uq_inhabitant_identity UNIQUE (inhabitant_id),
    CONSTRAINT stocked_quantity CHECK (quantity > 0),
    CONSTRAINT tank_inhabitants FOREIGN KEY (tank_id) REFERENCES aquarium_tank__tank(tank_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_aquarium_tank__inhabitant_captured_at ON aquarium_tank__inhabitant(captured_at);

CREATE TABLE IF NOT EXISTS aquarium_tank__water_test (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    test_id TEXT NOT NULL,
    tank_id TEXT NOT NULL,
    tested_at TEXT NOT NULL,
    ph REAL NOT NULL,
    ammonia_ppm REAL,
    nitrite_ppm REAL,
    nitrate_ppm REAL,
    temperature_f REAL,
    kh_dkh REAL,
    gh_dgh REAL,
    method TEXT NOT NULL CHECK (method IN ('liquid_kit', 'test_strip', 'probe')),
    notes TEXT,
    CONSTRAINT uq_water_test_identity UNIQUE (test_id),
    CONSTRAINT ph_in_range CHECK (ph > 0 AND ph < 14),
    CONSTRAINT nonnegative_nitrogen CHECK (ammonia_ppm >= 0 AND nitrite_ppm >= 0 AND nitrate_ppm >= 0),
    CONSTRAINT tank_tests FOREIGN KEY (tank_id) REFERENCES aquarium_tank__tank(tank_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_aquarium_tank__water_test_captured_at ON aquarium_tank__water_test(captured_at);

CREATE TABLE IF NOT EXISTS aquarium_tank__maintenance (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    maintenance_id TEXT NOT NULL,
    tank_id TEXT NOT NULL,
    done_at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('water_change', 'filter_clean', 'dosing', 'trim')),
    water_change_pct REAL,
    product TEXT,
    notes TEXT,
    CONSTRAINT uq_maintenance_identity UNIQUE (maintenance_id),
    CONSTRAINT water_change_fraction CHECK (water_change_pct > 0 AND water_change_pct <= 100),
    CONSTRAINT tank_maintenance FOREIGN KEY (tank_id) REFERENCES aquarium_tank__tank(tank_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_aquarium_tank__maintenance_captured_at ON aquarium_tank__maintenance(captured_at);

CREATE TABLE IF NOT EXISTS aquarium_tank__equipment (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_uid TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1)),
    equipment_id TEXT NOT NULL,
    tank_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('filter', 'heater', 'light', 'co2', 'air_pump')),
    name TEXT NOT NULL,
    rating TEXT,
    setpoint_f REAL,
    installed_at TEXT,
    last_serviced_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'serviced', 'retired')),
    CONSTRAINT uq_equipment_identity UNIQUE (equipment_id),
    CONSTRAINT tank_equipment FOREIGN KEY (tank_id) REFERENCES aquarium_tank__tank(tank_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_aquarium_tank__equipment_captured_at ON aquarium_tank__equipment(captured_at);

CREATE INDEX IF NOT EXISTS tank_parameter_trend ON aquarium_tank__water_test(tank_id, tested_at);
CREATE INDEX IF NOT EXISTS tank_maintenance_cadence ON aquarium_tank__maintenance(tank_id, kind, done_at);
CREATE INDEX IF NOT EXISTS tank_stocking ON aquarium_tank__inhabitant(tank_id, status);
