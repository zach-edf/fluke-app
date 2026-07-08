from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tests.unit._helpers import PACKAGES  # noqa: F401 - ensures sys.path setup

from fluke_app.alerts import AlertConfig, AlertEvaluator, AlertKind
from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.reading import Reading

_BASE = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _reading(
    value: float | None,
    *,
    at: datetime | None = None,
    unit: str = "V",
    status: ReadingStatus = ReadingStatus.OK,
    measurement_type: MeasurementType = MeasurementType.VOLTAGE_DC,
) -> Reading:
    return Reading(
        timestamp_utc=at or _BASE,
        value=value,
        unit=unit,
        measurement_type=measurement_type,
        status=status,
        display_text=f"{value} {unit}" if value is not None else "OL",
        source_device_id="dev-1",
    )


class AlertEvaluatorTests(unittest.TestCase):
    def test_high_threshold_crossing(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(high=120.0))
        below = evaluator.evaluate(_reading(100.0))
        self.assertFalse(below.active)

        above = evaluator.evaluate(_reading(130.0))
        self.assertTrue(above.active)
        self.assertEqual(above.kind, AlertKind.HIGH)
        self.assertTrue(above.just_triggered)
        self.assertIn("HIGH ALERT", above.message)

    def test_low_threshold_crossing(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(low=10.0))
        result = evaluator.evaluate(_reading(5.0))
        self.assertTrue(result.active)
        self.assertEqual(result.kind, AlertKind.LOW)
        self.assertTrue(result.just_triggered)

    def test_rising_edge_only_fires_once(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(high=120.0))
        first = evaluator.evaluate(_reading(130.0))
        second = evaluator.evaluate(_reading(131.0))
        self.assertTrue(first.just_triggered)
        self.assertTrue(second.active)
        self.assertFalse(second.just_triggered)

    def test_clearing_reports_just_cleared(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(high=120.0))
        evaluator.evaluate(_reading(130.0))
        cleared = evaluator.evaluate(_reading(100.0))
        self.assertFalse(cleared.active)
        self.assertTrue(cleared.just_cleared)

    def test_debounce_suppresses_short_spike(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(high=120.0, debounce_seconds=2.0))
        pending = evaluator.evaluate(_reading(130.0, at=_BASE))
        self.assertFalse(pending.active)
        self.assertTrue(pending.pending)

        # Value returns to normal before the debounce window elapses.
        recovered = evaluator.evaluate(_reading(100.0, at=_BASE + timedelta(seconds=1)))
        self.assertFalse(recovered.active)
        self.assertFalse(recovered.pending)

    def test_debounce_fires_after_sustained_breach(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(high=120.0, debounce_seconds=2.0))
        evaluator.evaluate(_reading(130.0, at=_BASE))
        still_pending = evaluator.evaluate(_reading(131.0, at=_BASE + timedelta(seconds=1)))
        self.assertFalse(still_pending.active)
        fired = evaluator.evaluate(_reading(132.0, at=_BASE + timedelta(seconds=2.5)))
        self.assertTrue(fired.active)
        self.assertTrue(fired.just_triggered)

    def test_over_range_status_alert(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(status_alerts=True))
        result = evaluator.evaluate(_reading(None, status=ReadingStatus.OVER_RANGE))
        self.assertTrue(result.active)
        self.assertEqual(result.kind, AlertKind.STATUS)
        self.assertIn("over-range", result.message)

    def test_status_alerts_disabled(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(status_alerts=False))
        result = evaluator.evaluate(_reading(None, status=ReadingStatus.OVER_RANGE))
        self.assertFalse(result.active)

    def test_status_takes_priority_over_value(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(high=120.0, status_alerts=True))
        # A reading can be over-range with no numeric value.
        result = evaluator.evaluate(_reading(None, status=ReadingStatus.OVER_RANGE))
        self.assertEqual(result.kind, AlertKind.STATUS)

    def test_connection_lost_alert(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(connection_alerts=True))
        result = evaluator.note_connection_lost("adapter reset")
        self.assertTrue(result.active)
        self.assertEqual(result.kind, AlertKind.CONNECTION_LOST)
        self.assertIn("adapter reset", result.message)

        restored = evaluator.note_connection_restored()
        self.assertFalse(restored.active)
        self.assertTrue(restored.just_cleared)

    def test_connection_alert_disabled(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(connection_alerts=False))
        result = evaluator.note_connection_lost()
        self.assertFalse(result.active)

    def test_switching_high_to_low_is_new_episode(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(high=120.0, low=10.0))
        high = evaluator.evaluate(_reading(130.0))
        low = evaluator.evaluate(_reading(5.0))
        self.assertTrue(high.just_triggered)
        self.assertTrue(low.just_triggered)
        self.assertEqual(low.kind, AlertKind.LOW)

    def test_invalid_config_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AlertEvaluator(AlertConfig(high=10.0, low=20.0))

    def test_set_config_resets_state(self) -> None:
        evaluator = AlertEvaluator(AlertConfig(high=120.0))
        evaluator.evaluate(_reading(130.0))
        evaluator.set_config(AlertConfig(high=200.0))
        result = evaluator.evaluate(_reading(130.0))
        self.assertFalse(result.active)


if __name__ == "__main__":
    unittest.main()
