from __future__ import annotations

import csv
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tests.unit._helpers import measurement_payload

from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.device import DeviceInfo
from fluke_protocol.profiles.fluke_376fc import FLUKE_MEAS_UUID, Fluke376FCProfile
from fluke_testing import MemorySessionCapture


class CaptureExportTests(unittest.TestCase):
    def test_capture_exports_csv_and_json(self) -> None:
        device = DeviceInfo(
            device_id="meter-1",
            ble_address="AA:BB:CC:DD:EE:FF",
            model_name="Fluke 376 FC",
            profile_id="fluke_376fc",
            nickname="Bench Meter",
            support_level="supported",
        )
        capture = MemorySessionCapture(
            device=device,
            title="Battery Pack Log",
            notes="replay run",
            tags=["battery", "bench"],
            app_version="0.1.0",
            profile_id="fluke_376fc",
        )

        profile = Fluke376FCProfile()
        reading = profile.parse_notification(
            FLUKE_MEAS_UUID,
            measurement_payload("12.34 V", "dc"),
            device.device_id,
            observed_at=datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc),
        )[0]
        capture.record(reading)
        session = capture.stop()

        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        csv_path = capture.export_csv(tmp / "session.csv")
        json_path = capture.export_json(tmp / "session.json")

        self.assertEqual(session.session_id, capture.session_id)
        self.assertIsNotNone(session.ended_at)

        with csv_path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["measurement_type"], MeasurementType.VOLTAGE_DC.value)
        self.assertEqual(rows[0]["status"], ReadingStatus.OK.value)
        self.assertEqual(rows[0]["raw_payload"], measurement_payload("12.34 V", "dc").hex())

        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(data["session"]["title"], "Battery Pack Log")
        self.assertEqual(data["session"]["profile_id"], "fluke_376fc")
        self.assertEqual(data["device"]["ble_address"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(data["readings"][0]["measurement_type"], MeasurementType.VOLTAGE_DC.value)
        self.assertEqual(data["readings"][0]["display_text"], "12.34 V")


if __name__ == "__main__":
    unittest.main()
