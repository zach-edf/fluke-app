from __future__ import annotations

SCHEMA_VERSION = 4

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    ble_address TEXT NOT NULL,
    model_name TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    family_id TEXT NOT NULL DEFAULT '',
    variant_id TEXT NOT NULL DEFAULT '',
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
    asset_id TEXT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE RESTRICT,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE SET NULL
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
    source_device_id TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    raw_payload BLOB NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS session_markers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    label TEXT NOT NULL,
    note TEXT NOT NULL,
    source TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_readings_session_time
    ON readings(session_id, timestamp_utc);

CREATE INDEX IF NOT EXISTS idx_sessions_device_started
    ON sessions(device_id, started_at);

CREATE INDEX IF NOT EXISTS idx_markers_session_time
    ON session_markers(session_id, timestamp_utc);

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    result TEXT NOT NULL,
    workflow_title TEXT,
    asset_id TEXT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS workflow_step_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    completed_at TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT,
    reading_json TEXT,
    FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_session_started
    ON workflow_runs(session_id, started_at);

CREATE INDEX IF NOT EXISTS idx_workflow_step_results_run_step
    ON workflow_step_results(run_id, step_index, completed_at);
"""
