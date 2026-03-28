from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
