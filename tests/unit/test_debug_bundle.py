from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from uuid import uuid4
import zipfile

from fluke_app import export_debug_bundle, load_workflow_catalog, new_session
from fluke_core.models.device import DeviceInfo
from fluke_plugins import build_profile_registry, load_plugin_bundle
from fluke_store import FlukeStore


class DebugBundleTests(unittest.TestCase):
    def test_export_debug_bundle_writes_expected_files(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "bundle.db")
        try:
            store.upsert_device(
                DeviceInfo(
                    device_id="meter-1",
                    ble_address="AA:BB:CC:DD:EE:FF",
                    model_name="Fluke 376 FC",
                    profile_id="fluke_376fc",
                    nickname="Bench Meter",
                    support_level="supported",
                ),
                last_seen_at=datetime.now(timezone.utc),
            )
            store.sessions.create(new_session(device_id="meter-1", title="Bundle Session", profile_id="fluke_376fc"))

            output = Path(
                export_debug_bundle(
                    tmp / "debug-bundle.zip",
                    profile_registry=build_profile_registry(),
                    workflow_catalog=load_workflow_catalog(),
                    plugin_bundle=load_plugin_bundle(),
                    database_path=store.path,
                )
            )
        finally:
            store.close()

        self.assertTrue(output.exists())
        with zipfile.ZipFile(output, "r") as bundle:
            names = set(bundle.namelist())
            self.assertTrue({"manifest.json", "profiles.json", "workflows.json", "plugins.json"} <= names)
            manifest = json.loads(bundle.read("manifest.json").decode("utf-8"))
            profiles = json.loads(bundle.read("profiles.json").decode("utf-8"))
            self.assertEqual(Path(manifest["database_path"]).name, "bundle.db")
            self.assertIn("fluke_376fc", [item["profile_id"] for item in profiles])
            if "store_snapshot.json" in names:
                snapshot = json.loads(bundle.read("store_snapshot.json").decode("utf-8"))
                self.assertEqual(len(snapshot["sessions"]), 1)


if __name__ == "__main__":
    unittest.main()
