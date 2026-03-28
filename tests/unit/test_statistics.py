from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.reading import Reading
from fluke_core.services.statistics import summarize_readings


class SessionStatisticsTests(unittest.TestCase):
    def test_summarize_readings_handles_numeric_and_missing_values(self) -> None:
        t0 = datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc)
        readings = [
            Reading(
                timestamp_utc=t0,
                value=12.0,
                unit="V",
                measurement_type=MeasurementType.VOLTAGE_DC,
                status=ReadingStatus.OK,
                display_text="12.0 V",
                source_device_id="meter-1",
            ),
            Reading(
                timestamp_utc=t0 + timedelta(seconds=2),
                value=None,
                unit="V",
                measurement_type=MeasurementType.VOLTAGE_DC,
                status=ReadingStatus.UNSTABLE,
                display_text="OL",
                source_device_id="meter-1",
            ),
            Reading(
                timestamp_utc=t0 + timedelta(seconds=5),
                value=15.0,
                unit="V",
                measurement_type=MeasurementType.VOLTAGE_DC,
                status=ReadingStatus.OK,
                display_text="15.0 V",
                source_device_id="meter-1",
            ),
        ]

        stats = summarize_readings(readings)

        self.assertEqual(stats.reading_count, 3)
        self.assertEqual(stats.numeric_count, 2)
        self.assertEqual(stats.min_value, 12.0)
        self.assertEqual(stats.max_value, 15.0)
        self.assertEqual(stats.avg_value, 13.5)
        self.assertEqual(stats.duration_s, 5.0)

    def test_summarize_readings_empty_input_returns_defaults(self) -> None:
        stats = summarize_readings([])
        self.assertEqual(stats.reading_count, 0)
        self.assertEqual(stats.numeric_count, 0)
        self.assertIsNone(stats.min_value)
        self.assertIsNone(stats.max_value)
        self.assertIsNone(stats.avg_value)
        self.assertEqual(stats.duration_s, 0.0)


if __name__ == "__main__":
    unittest.main()
