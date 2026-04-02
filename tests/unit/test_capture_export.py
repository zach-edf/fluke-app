from __future__ import annotations

import csv
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tests.unit._helpers import measurement_payload

from fluke_app import ExportService, new_session
from fluke_app.export_service import SessionCsvExporter, SessionJsonExporter
from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.device import DeviceInfo
from fluke_core.models.marker import SessionMarker
from fluke_core.models.reading import Reading
from fluke_protocol.profiles.fluke_376fc import FLUKE_MEAS_UUID, Fluke376FCProfile
from fluke_store import FlukeStore
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

    def test_export_service_writes_analysis_csv_and_segment_summary_json(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "exports.db")
        try:
            device = DeviceInfo(
                device_id="meter-export",
                ble_address="AA:BB:CC:DD:EE:01",
                model_name="Fluke 376 FC",
                profile_id="fluke_376fc",
                nickname="Bench Meter",
                support_level="supported",
            )
            store.upsert_device(device)
            session = new_session(device_id=device.device_id, title="Mixed Export Session", profile_id="fluke_376fc")
            store.sessions.create(session)

            readings = [
                _store_reading(1.2, "kOhm", MeasurementType.RESISTANCE, 0, mode="", unit_family="resistance"),
                _store_reading(1300.0, "ohm", MeasurementType.RESISTANCE, 1, mode="dc", unit_family="resistance"),
                _store_reading(12.34, "V", MeasurementType.VOLTAGE_DC, 8, mode="dc", unit_family="voltage"),
            ]
            for reading in readings:
                store.readings.append(session.session_id, reading)

            store.markers.append(
                session.session_id,
                SessionMarker(
                    session_id=session.session_id,
                    timestamp_utc=datetime(2026, 3, 27, 12, 0, 0, 500000, tzinfo=timezone.utc),
                    label="note",
                    note="Resistance marker",
                ),
            )
            store.markers.append(
                session.session_id,
                SessionMarker(
                    session_id=session.session_id,
                    timestamp_utc=datetime(2026, 3, 27, 12, 0, 8, tzinfo=timezone.utc),
                    label="workflow",
                    note="Voltage marker",
                    source="workflow",
                ),
            )

            service = ExportService(
                store.sessions,
                store.readings,
                store.markers,
                SessionCsvExporter(),
                SessionJsonExporter(device_repo=store.devices),
            )

            analysis_path = Path(service.export_analysis_csv(session.session_id, tmp / "analysis.csv"))
            segments_path = Path(service.export_segment_summary_json(session.session_id, tmp / "segments.json"))

            with analysis_path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(
                rows[0].keys(),
                {"timestamp_utc", "resistance_kohm", "voltage_dc_v"},
            )
            self.assertEqual(rows[0]["resistance_kohm"], "1.2")
            self.assertEqual(rows[1]["resistance_kohm"], "1.3")
            self.assertEqual(rows[2]["voltage_dc_v"], "12.34")

            payload = json.loads(segments_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["segment_count"], 2)
            self.assertEqual(payload["segments"][0]["context_id"], "resistance")
            self.assertEqual(payload["segments"][0]["sample_count"], 2)
            self.assertEqual(payload["segments"][1]["context_id"], "voltage_dc")
            self.assertEqual(payload["segments"][1]["sample_count"], 1)
            self.assertEqual(payload["segments"][0]["markers"][0]["note"], "Resistance marker")
            self.assertEqual(payload["segments"][1]["markers"][0]["source"], "workflow")
        finally:
            store.close()


def _store_reading(
    value: float,
    unit: str,
    measurement_type: MeasurementType,
    second: int,
    *,
    mode: str,
    unit_family: str,
) -> Reading:
    return Reading(
        timestamp_utc=datetime(2026, 3, 27, 12, 0, second, tzinfo=timezone.utc),
        value=value,
        unit=unit,
        measurement_type=measurement_type,
        status=ReadingStatus.OK,
        display_text=f"{value:g} {unit}".strip(),
        source_device_id="meter-export",
        mode=mode,
        metadata={"unit_family": unit_family},
    )


if __name__ == "__main__":
    unittest.main()
