from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
import threading

from fluke_core.models.device import DeviceInfo
from fluke_core.models.marker import SessionMarker
from fluke_core.models.reading import Reading
from fluke_core.models.session import Session
from fluke_core.models.asset import Asset
from fluke_core.models.workflow import WorkflowRun, WorkflowStepResult
from fluke_store.repositories.assets import AssetRepository
from fluke_store.repositories.devices import DeviceRepository
from fluke_store.repositories.markers import MarkerRepository
from fluke_store.repositories.readings import ReadingRepository
from fluke_store.repositories.sessions import SessionRepository
from fluke_store.repositories.workflow_runs import WorkflowRunRepository
from fluke_store.repositories.workflow_step_results import WorkflowStepResultRepository
from fluke_store.schema import SCHEMA_SQL


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def initialize(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA_SQL)
    _ensure_column(con, "devices", "family_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "devices", "variant_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "readings", "source_device_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "readings", "mode", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "readings", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    # Asset linkage was added in schema v4. Existing sessions and workflow runs
    # remain assetless (NULL) until a user attaches them to an asset.
    _ensure_column(con, "sessions", "asset_id", "TEXT NULL")
    _ensure_column(con, "workflow_runs", "asset_id", "TEXT NULL")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_asset_started ON sessions(asset_id, started_at)"
    )
    con.commit()


def _ensure_column(con: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {
        row["name"]
        for row in con.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column in existing:
        return
    con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


class FlukeStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.con = connect(self.path)
        initialize(self.con)
        self._lock = threading.RLock()
        self.assets = AssetRepository(self.con, lock=self._lock)
        self.devices = DeviceRepository(self.con, lock=self._lock)
        self.markers = MarkerRepository(self.con, lock=self._lock)
        self.sessions = SessionRepository(self.con, lock=self._lock)
        self.readings = ReadingRepository(self.con, lock=self._lock)
        self.workflow_runs = WorkflowRunRepository(self.con, lock=self._lock)
        self.workflow_step_results = WorkflowStepResultRepository(self.con, lock=self._lock)

    def close(self) -> None:
        self.con.close()

    def upsert_device(self, device: DeviceInfo, last_seen_at: datetime | None = None) -> DeviceInfo:
        return self.devices.upsert(device, last_seen_at=last_seen_at)

    def create_asset(self, asset: Asset) -> Asset:
        return self.assets.create(asset)

    def create_session(self, session: Session) -> Session:
        return self.sessions.create(session)

    def add_reading(self, session_id: str, reading: Reading) -> Reading:
        return self.readings.append(session_id, reading)

    def add_marker(self, session_id: str, marker: SessionMarker) -> SessionMarker:
        return self.markers.append(session_id, marker)

    def create_workflow_run(self, run: WorkflowRun) -> WorkflowRun:
        return self.workflow_runs.create(run)

    def add_workflow_step_result(self, result: WorkflowStepResult) -> WorkflowStepResult:
        return self.workflow_step_results.append(result)

    def export_snapshot(
        self,
        session_ids: Iterable[str] | None = None,
    ) -> dict[str, list]:
        device_ids: list[str] = []
        sessions: list[Session] = []
        readings: list[Reading] = []

        if session_ids is None:
            sessions = self.sessions.list_recent(limit=500)
        else:
            for session_id in session_ids:
                session = self.sessions.get(session_id)
                if session is not None:
                    sessions.append(session)

        seen_devices: set[str] = set()
        for session in sessions:
            if session.device_id not in seen_devices:
                seen_devices.add(session.device_id)
                device_ids.append(session.device_id)
            readings.extend(self.readings.list_for_session(session.session_id))

        devices = [device for device_id in device_ids if (device := self.devices.get(device_id)) is not None]
        markers = []
        workflow_runs = []
        workflow_step_results = []
        for session in sessions:
            markers.extend(self.markers.list_for_session(session.session_id))
            workflow_runs.extend(self.workflow_runs.list_for_session(session.session_id))
        for workflow_run in workflow_runs:
            workflow_step_results.extend(self.workflow_step_results.list_for_run(workflow_run.run_id))
        return {
            "devices": devices,
            "sessions": sessions,
            "readings": readings,
            "markers": markers,
            "workflow_runs": workflow_runs,
            "workflow_step_results": workflow_step_results,
        }
