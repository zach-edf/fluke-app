from __future__ import annotations

import sqlite3
import threading
import unittest
from pathlib import Path
from uuid import uuid4

from fluke_store import FlukeStore


class StorePathTests(unittest.TestCase):
    def test_store_creates_parent_directory(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        db_path = tmp_root / uuid4().hex / "nested" / "fluke.db"
        store = FlukeStore(db_path)
        try:
            self.assertTrue(db_path.exists())
        finally:
            store.close()

    def test_store_migrates_existing_readings_table_for_decoded_fields(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        db_path = tmp_root / uuid4().hex / "legacy" / "fluke.db"
        db_path.parent.mkdir(parents=True, exist_ok=False)

        con = sqlite3.connect(db_path)
        try:
            con.executescript(
                """
                CREATE TABLE readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    value REAL NULL,
                    unit TEXT NOT NULL,
                    measurement_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    display_text TEXT NOT NULL,
                    raw_payload BLOB NULL
                );
                """
            )
            con.commit()
        finally:
            con.close()

        store = FlukeStore(db_path)
        try:
            columns = {
                row["name"]
                for row in store.con.execute("PRAGMA table_info(readings)").fetchall()
            }
            self.assertIn("source_device_id", columns)
            self.assertIn("mode", columns)
            self.assertIn("metadata_json", columns)
        finally:
            store.close()

    def test_store_allows_cross_thread_reads(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        db_path = tmp_root / uuid4().hex / "threaded" / "fluke.db"
        store = FlukeStore(db_path)
        errors: list[Exception] = []

        def worker() -> None:
            try:
                store.sessions.list_recent(limit=1)
                store.devices.list_recent(limit=1)
            except Exception as exc:  # pragma: no cover - assertion below checks this stays empty
                errors.append(exc)

        try:
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
