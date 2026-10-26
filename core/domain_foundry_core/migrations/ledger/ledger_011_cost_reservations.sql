-- Durable admission holds. Unknown outcomes remain held until reconciled.
CREATE TABLE cost_reservation (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL,
    tier TEXT,
    amount_usd REAL NOT NULL CHECK (amount_usd > 0),
    status TEXT NOT NULL CHECK (status IN ('held', 'settled', 'released', 'overrun')),
    created_at TEXT NOT NULL,
    settled_at TEXT
);
CREATE INDEX cost_reservation_day_status ON cost_reservation(day, status);
