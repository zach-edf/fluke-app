from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tests.unit._helpers import ROOT  # noqa: F401  (ensures sys.path is set up)

from fluke_app import new_session
from fluke_core.models.asset import Asset
from fluke_core.models.device import DeviceInfo
from fluke_store import FlukeStore
from fluke_store.schema import SCHEMA_VERSION


def _tmp_dir() -> Path:
    tmp = Path(__file__).resolve().parents[2] / ".test-tmp" / uuid4().hex
    tmp.mkdir(parents=True, exist_ok=False)
    return tmp


# SQL for a pre-asset (schema v3) database, used to exercise the migration path.
_LEGACY_SCHEMA_SQL = """
CREATE TABLE devices (
    id TEXT PRIMARY KEY, ble_address TEXT NOT NULL, model_name TEXT NOT NULL,
    profile_id TEXT NOT NULL, family_id TEXT NOT NULL DEFAULT '',
    variant_id TEXT NOT NULL DEFAULT '', nickname TEXT, firmware_version TEXT,
    serial_number TEXT, support_level TEXT NOT NULL, last_seen_at TEXT
);
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, started_at TEXT NOT NULL,
    ended_at TEXT, title TEXT, notes TEXT, tags_json TEXT NOT NULL,
    app_version TEXT, profile_id TEXT
);
CREATE TABLE readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL, value REAL, unit TEXT NOT NULL,
    measurement_type TEXT NOT NULL, status TEXT NOT NULL, display_text TEXT NOT NULL
);
CREATE TABLE workflow_runs (
    run_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, session_id TEXT NOT NULL,
    started_at TEXT NOT NULL, ended_at TEXT, result TEXT NOT NULL, workflow_title TEXT
);
INSERT INTO devices VALUES ('d1','AA','M','p','','',NULL,NULL,NULL,'supported',NULL);
INSERT INTO sessions VALUES ('s_old','d1','2026-01-01T00:00:00+00:00',NULL,'Old',NULL,'[]','0.1',NULL);
"""


class AssetRepositoryTests(unittest.TestCase):
    def test_asset_crud_roundtrip(self) -> None:
        store = FlukeStore(_tmp_dir() / "assets.db")
        try:
            created = store.create_asset(
                Asset(asset_id="motor-1", name="Line 3 Motor", asset_type="motor", location="Bay 2", notes="n")
            )
            self.assertIsNotNone(created.created_at)

            fetched = store.assets.get("motor-1")
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.name, "Line 3 Motor")
            self.assertEqual(fetched.asset_type, "motor")
            self.assertEqual(fetched.location, "Bay 2")

            # update via create (upsert)
            store.assets.update(Asset(asset_id="motor-1", name="Renamed", created_at=created.created_at))
            self.assertEqual(store.assets.get("motor-1").name, "Renamed")

            self.assertEqual([a.asset_id for a in store.assets.list_all()], ["motor-1"])
        finally:
            store.close()

    def test_assign_and_list_for_asset(self) -> None:
        store = FlukeStore(_tmp_dir() / "assign.db")
        try:
            store.upsert_device(
                DeviceInfo(device_id="d1", ble_address="AA", model_name="M", profile_id="p", support_level="supported")
            )
            store.create_asset(Asset(asset_id="a1", name="Asset One"))

            linked = new_session(device_id="d1", title="linked", asset_id="a1")
            unlinked = new_session(device_id="d1", title="unlinked")
            store.sessions.create(linked)
            store.sessions.create(unlinked)

            listed = store.sessions.list_for_asset("a1")
            self.assertEqual([s.session_id for s in listed], [linked.session_id])
            self.assertEqual(store.sessions.get(linked.session_id).asset_id, "a1")

            # retroactive assignment + clearing
            store.sessions.assign_asset(unlinked.session_id, "a1")
            self.assertEqual({s.session_id for s in store.sessions.list_for_asset("a1")}, {linked.session_id, unlinked.session_id})
            store.sessions.assign_asset(unlinked.session_id, None)
            self.assertEqual([s.session_id for s in store.sessions.list_for_asset("a1")], [linked.session_id])
        finally:
            store.close()

    def test_delete_asset_detaches_sessions(self) -> None:
        store = FlukeStore(_tmp_dir() / "delete.db")
        try:
            store.upsert_device(
                DeviceInfo(device_id="d1", ble_address="AA", model_name="M", profile_id="p", support_level="supported")
            )
            store.create_asset(Asset(asset_id="a1", name="Asset One"))
            session = new_session(device_id="d1", asset_id="a1")
            store.sessions.create(session)

            store.assets.delete("a1")
            self.assertIsNone(store.assets.get("a1"))
            self.assertIsNone(store.sessions.get(session.session_id).asset_id)
        finally:
            store.close()

    def test_migration_from_legacy_schema(self) -> None:
        db_path = _tmp_dir() / "legacy.db"
        con = sqlite3.connect(db_path)
        con.executescript(_LEGACY_SCHEMA_SQL)
        con.commit()
        con.close()

        # Opening through FlukeStore must migrate cleanly and keep old data.
        store = FlukeStore(db_path)
        try:
            self.assertGreaterEqual(SCHEMA_VERSION, 4)
            old = store.sessions.get("s_old")
            self.assertIsNotNone(old)
            self.assertIsNone(old.asset_id)  # old sessions remain assetless

            # New asset machinery works on the upgraded database.
            store.create_asset(Asset(asset_id="a1", name="Migrated Asset"))
            store.sessions.assign_asset("s_old", "a1")
            self.assertEqual(store.sessions.get("s_old").asset_id, "a1")

            cols = {row["name"] for row in store.con.execute("PRAGMA table_info(workflow_runs)").fetchall()}
            self.assertIn("asset_id", cols)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
