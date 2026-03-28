from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from uuid import uuid4

from tests.unit._helpers import measurement_payload

from fluke_app import DeviceManager, ExportService, SessionRecorder, new_session
from fluke_app.export_service import SessionCsvExporter, SessionJsonExporter
from fluke_ble.adapter import BleDevice
from fluke_protocol import ProfileRegistry
from fluke_protocol.profiles.fluke_376fc import FLUKE_MEAS_UUID, FLUKE_STATUS_UUID, Fluke376FCProfile
from fluke_store import FlukeStore
from fluke_testing import FakeBleAdapter, ReplayFrame, ReplayScenario


class LoggingFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_replayed_session_persists_and_exports(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        db_path = tmp / "fluke.db"
        store = FlukeStore(db_path)
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-1",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:FF",
                    rssi=-44,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        recorder = SessionRecorder(store.sessions, store.readings, store.markers)
        exporter = ExportService(
            store.sessions,
            store.readings,
            store.markers,
            SessionCsvExporter(),
            SessionJsonExporter(device_repo=store.devices),
        )

        try:
            devices = await manager.scan()
            device = await manager.connect(devices[0].device_id)
            store.upsert_device(device)

            session = recorder.start(
                new_session(
                    device_id=device.device_id,
                    title="Replay Session",
                    notes="integration test",
                    tags=["test", "replay"],
                    profile_id=device.profile_id,
                )
            )

            manager.subscribe_readings(recorder.on_reading)
            await manager.start_stream()

            scenario = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x17])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.34 V", "dc")),
                )
            )
            await scenario.run(adapter, device.device_id)
            marker = recorder.add_marker("Clamp repositioned")

            ended = recorder.stop()
            await manager.disconnect()

            self.assertIsNotNone(ended)
            self.assertEqual(recorder.reading_count(), 1)
            self.assertEqual(store.sessions.get(session.session_id).title, "Replay Session")
            self.assertEqual(marker.note, "Clamp repositioned")

            readings = store.readings.list_for_session(session.session_id)
            markers = store.markers.list_for_session(session.session_id)
            self.assertEqual(len(readings), 1)
            self.assertEqual(len(markers), 1)
            self.assertEqual(readings[0].display_text, "12.34 V")
            self.assertEqual(readings[0].source_device_id, device.device_id)
            self.assertEqual(readings[0].mode, "dc")
            self.assertEqual(readings[0].metadata["function_key"], "dc_voltage")

            csv_path = Path(exporter.export_csv(session.session_id, tmp / "session.csv"))
            json_path = Path(exporter.export_json(session.session_id, tmp / "session.json"))

            with csv_path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["session_id"], session.session_id)
            self.assertEqual(rows[0]["source_device_id"], device.device_id)
            self.assertEqual(rows[0]["mode"], "dc")

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["session"]["session_id"], session.session_id)
            self.assertEqual(payload["device"]["device_id"], device.device_id)
            self.assertEqual(payload["device"]["support_level"], "supported")
            self.assertEqual(payload["statistics"]["reading_count"], 1)
            self.assertEqual(payload["statistics"]["min_value"], 12.34)
            self.assertEqual(len(payload["readings"]), 1)
            self.assertEqual(payload["readings"][0]["source_device_id"], device.device_id)
            self.assertEqual(payload["readings"][0]["mode"], "dc")
            self.assertEqual(payload["readings"][0]["metadata"]["function_key"], "dc_voltage")
            self.assertEqual(len(payload["markers"]), 1)
            self.assertEqual(payload["markers"][0]["note"], "Clamp repositioned")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
