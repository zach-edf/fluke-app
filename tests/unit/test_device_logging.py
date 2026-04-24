from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

from apps.cli.main import build_parser
from fluke_app.device_logging import build_logging_session_previews, import_logging_sessions
from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_protocol.profiles.fluke_376fc import decode_logging_download_payload
from fluke_store import FlukeStore


_SINGLE_SESSION_PAYLOAD = bytes.fromhex(
    "01 04 00 00 a5 00 6b 1c d7 69 99 1c d7 69 12 00 00 00 "
    "20 01 01 01 00 00 04 00 fe ff 06 00 00 00 00 00 00 00"
)


class DeviceLoggingImportTests(unittest.TestCase):
    def test_import_logging_sessions_persists_session_and_readings(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "device-memory.db")
        try:
            decoded = decode_logging_download_payload(_SINGLE_SESSION_PAYLOAD)
            report = import_logging_sessions(
                device_repo=store.devices,
                session_repo=store.sessions,
                reading_repo=store.readings,
                device_id="meter-memory",
                decoded_sessions=decoded,
                value_source="average",
            )

            self.assertEqual(report["imported_count"], 1)
            self.assertEqual(report["skipped_count"], 0)
            session_id = report["imported_sessions"][0]["session_id"]
            session = store.sessions.get(session_id)
            self.assertIsNotNone(session)
            self.assertEqual(session.title, "Device Memory A DC 2026-04-09 03:26:35Z")
            self.assertEqual(session.profile_id, "fluke_376fc")

            device = store.devices.get("meter-memory")
            self.assertIsNotNone(device)
            self.assertEqual(device.model_name, "Fluke 376 FC")
            self.assertEqual(device.family_id, "fluke_clamp_meter")
            self.assertEqual(device.variant_id, "376fc")

            readings = store.readings.list_for_session(session_id)
            self.assertEqual(len(readings), 1)
            reading = readings[0]
            self.assertEqual(reading.measurement_type, MeasurementType.CURRENT_DC)
            self.assertEqual(reading.status, ReadingStatus.OK)
            self.assertEqual(reading.unit, "A")
            self.assertEqual(reading.mode, "dc")
            self.assertEqual(reading.display_text, "0 A")
            self.assertAlmostEqual(reading.value or 0.0, 0.0)
            self.assertEqual(reading.metadata["source"], "device_memory")
            self.assertEqual(reading.metadata["value_source"], "average")
            self.assertEqual(reading.metadata["unit_family"], "current")
            self.assertEqual(reading.metadata["average"]["scaled_value"], 0.0)
            self.assertEqual(reading.metadata["maximum"]["scaled_value"], 0.4)
            self.assertEqual(reading.metadata["minimum"]["scaled_value"], -0.2)
            self.assertEqual(
                reading.raw_payload,
                bytes.fromhex("20 01 01 01 00 00 04 00 fe ff 06 00 00 00 00 00 00 00"),
            )
        finally:
            store.close()

    def test_import_logging_sessions_skips_duplicate_session(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "device-memory-dedupe.db")
        try:
            decoded = decode_logging_download_payload(_SINGLE_SESSION_PAYLOAD)
            first = import_logging_sessions(
                device_repo=store.devices,
                session_repo=store.sessions,
                reading_repo=store.readings,
                device_id="meter-memory",
                decoded_sessions=decoded,
            )
            second = import_logging_sessions(
                device_repo=store.devices,
                session_repo=store.sessions,
                reading_repo=store.readings,
                device_id="meter-memory",
                decoded_sessions=decoded,
            )

            self.assertEqual(first["imported_count"], 1)
            self.assertEqual(second["imported_count"], 0)
            self.assertEqual(second["skipped_count"], 1)
            self.assertEqual(second["skipped_sessions"][0]["reason"], "already_imported")
            self.assertEqual(len(store.sessions.list_recent(limit=10)), 1)
        finally:
            store.close()

    def test_build_logging_session_previews_marks_existing_imports(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "device-memory-preview.db")
        try:
            decoded = decode_logging_download_payload(_SINGLE_SESSION_PAYLOAD)
            import_logging_sessions(
                device_repo=store.devices,
                session_repo=store.sessions,
                reading_repo=store.readings,
                device_id="meter-memory",
                decoded_sessions=decoded,
            )
            previews = build_logging_session_previews(
                session_repo=store.sessions,
                device_id="meter-memory",
                decoded_sessions=decoded,
            )

            self.assertEqual(len(previews), 1)
            self.assertEqual(previews[0]["measurement_text"], "A DC")
            self.assertEqual(previews[0]["detail_count"], 1)
            self.assertEqual(previews[0]["import_status"], "Imported")
        finally:
            store.close()

    def test_cli_parser_accepts_sessions_import_device_memory(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "--json",
                "sessions",
                "import-device-memory",
                "--device",
                "meter-memory",
                "--value-source",
                "minimum",
                "--data-output",
                "artifacts/device-memory.bin",
                "--download-report-output",
                "artifacts/device-memory.json",
                "--max-blocks-per-request",
                "250",
                "--command-timeout-seconds",
                "6.5",
            ]
        )

        self.assertEqual(args.command, "sessions")
        self.assertEqual(args.sessions_command, "import-device-memory")
        self.assertTrue(args.json)
        self.assertEqual(args.device, "meter-memory")
        self.assertEqual(args.value_source, "minimum")
        self.assertEqual(args.data_output, "artifacts/device-memory.bin")
        self.assertEqual(args.download_report_output, "artifacts/device-memory.json")
        self.assertEqual(args.max_blocks_per_request, 250)
        self.assertEqual(args.command_timeout_seconds, 6.5)


if __name__ == "__main__":
    unittest.main()
