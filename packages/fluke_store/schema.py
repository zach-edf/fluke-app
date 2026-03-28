from __future__ import annotations

SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    ble_address TEXT NOT NULL,
    model_name TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    nickname TEXT NULL,
    firmware_version TEXT NULL,
    serial_number TEXT NULL,
    support_level TEXT NOT NULL,
    last_seen_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NULL,
    title TEXT NULL,
    notes TEXT NULL,
    tags_json TEXT NOT NULL,
    app_version TEXT NULL,
    profile_id TEXT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    value REAL NULL,
    unit TEXT NOT NULL,
    measurement_type TEXT NOT NULL,
    status TEXT NOT NULL,
    display_text TEXT NOT NULL,
    raw_payload BLOB NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_readings_session_time
    ON readings(session_id, timestamp_utc);

CREATE INDEX IF NOT EXISTS idx_sessions_device_started
    ON sessions(device_id, started_at);
"""

