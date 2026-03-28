from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ROOT / "packages"

for path in (ROOT, PACKAGES):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_protocol.profiles.fluke_376fc import FLUKE_MEAS_UUID, FLUKE_STATUS_UUID, Fluke376FCProfile


def measurement_payload(primary: str, mode: str) -> bytes:
    display = primary.ljust(10)[:10].encode("ascii")
    mode_bytes = mode.ljust(5)[:5].encode("ascii")
    return b"\x00" + display + b"\x00" + mode_bytes


class Fluke376FCProfileTests(unittest.TestCase):
    def test_matches_fluke_376_name(self) -> None:
        profile = Fluke376FCProfile()
        self.assertTrue(profile.matches("Fluke 376 FC", {}))
        self.assertTrue(profile.matches(None, {"advertisement_name": "Shop 376FC"}))
        self.assertFalse(profile.matches("Random Sensor", {}))

    def test_parse_dc_voltage_reading(self) -> None:
        profile = Fluke376FCProfile()
        observed_at = datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc)

        readings = profile.parse_notification(
            FLUKE_MEAS_UUID,
            measurement_payload("12.34 V", "dc"),
            "meter-1",
            observed_at=observed_at,
        )

        self.assertEqual(len(readings), 1)
        reading = readings[0]
        self.assertEqual(reading.timestamp_utc, observed_at)
        self.assertAlmostEqual(reading.value or 0.0, 12.34)
        self.assertEqual(reading.unit, "V")
        self.assertEqual(reading.measurement_type, MeasurementType.VOLTAGE_DC)
        self.assertEqual(reading.status, ReadingStatus.OK)
        self.assertEqual(reading.mode, "dc")
        self.assertEqual(reading.metadata["function_key"], "dc_voltage")

    def test_parse_over_range_reading(self) -> None:
        profile = Fluke376FCProfile()

        readings = profile.parse_notification(
            FLUKE_MEAS_UUID,
            measurement_payload("OL mV", "dc"),
            "meter-1",
        )

        self.assertEqual(len(readings), 1)
        reading = readings[0]
        self.assertIsNone(reading.value)
        self.assertEqual(reading.unit, "mV")
        self.assertEqual(reading.measurement_type, MeasurementType.VOLTAGE_DC)
        self.assertEqual(reading.status, ReadingStatus.OVER_RANGE)

    def test_status_notifications_are_cached_not_emitted(self) -> None:
        profile = Fluke376FCProfile()
        readings = profile.parse_notification(FLUKE_STATUS_UUID, bytes([123]), "meter-1")
        self.assertEqual(readings, [])


if __name__ == "__main__":
    unittest.main()
