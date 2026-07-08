from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tests.unit._helpers import ROOT  # noqa: F401

from fluke_app import AssetTrendService, new_session
from fluke_app.asset_trend_service import export_asset_trend_csv
from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.asset import Asset
from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_store import FlukeStore


def _tmp_dir() -> Path:
    tmp = Path(__file__).resolve().parents[2] / ".test-tmp" / uuid4().hex
    tmp.mkdir(parents=True, exist_ok=False)
    return tmp


def _reading(value, unit, mtype, month, second, unit_family) -> Reading:
    return Reading(
        timestamp_utc=datetime(2026, month, 1, 0, 0, second, tzinfo=timezone.utc),
        value=value,
        unit=unit,
        measurement_type=mtype,
        status=ReadingStatus.OK,
        display_text=f"{value} {unit}",
        source_device_id="d1",
        metadata={"unit_family": unit_family},
    )


class AssetTrendServiceTests(unittest.TestCase):
    def _store(self) -> FlukeStore:
        store = FlukeStore(_tmp_dir() / "trend.db")
        store.upsert_device(
            DeviceInfo(device_id="d1", ble_address="AA", model_name="M", profile_id="p", support_level="supported")
        )
        store.create_asset(Asset(asset_id="motor-1", name="Motor"))
        return store

    def _add_session(self, store, month, readings, *, asset_id="motor-1", title=None):
        session = new_session(
            device_id="d1",
            title=title or f"run-{month}",
            asset_id=asset_id,
            started_at=datetime(2026, month, 1, tzinfo=timezone.utc),
        )
        store.sessions.create(session)
        for reading in readings:
            store.readings.append(session.session_id, reading)
        return session

    def test_trend_aggregates_stats_per_session(self) -> None:
        store = self._store()
        try:
            self._add_session(store, 1, [
                _reading(40.0, "A", MeasurementType.CURRENT_INRUSH, 1, 0, "current"),
                _reading(42.0, "A", MeasurementType.CURRENT_INRUSH, 1, 1, "current"),
                _reading(44.0, "A", MeasurementType.CURRENT_INRUSH, 1, 2, "current"),
            ])
            self._add_session(store, 7, [
                _reading(50.0, "A", MeasurementType.CURRENT_INRUSH, 7, 0, "current"),
                _reading(51.0, "A", MeasurementType.CURRENT_INRUSH, 7, 1, "current"),
                _reading(52.0, "A", MeasurementType.CURRENT_INRUSH, 7, 2, "current"),
            ])

            trend = AssetTrendService(store.sessions, store.readings).build_trend("motor-1")
            self.assertEqual(trend.session_count, 2)
            self.assertEqual(len(trend.series), 1)
            series = trend.series[0]
            self.assertEqual(series.context_id, "current_inrush")
            self.assertEqual(series.unit, "A")
            self.assertEqual(len(series.points), 2)

            jan, jul = series.points
            self.assertEqual((jan.min_value, jan.max_value, jan.avg_value, jan.median_value), (40.0, 44.0, 42.0, 42.0))
            self.assertEqual((jul.min_value, jul.max_value, jul.avg_value, jul.median_value), (50.0, 52.0, 51.0, 51.0))
            # chronological x-axis
            self.assertLess(jan.started_at, jul.started_at)
        finally:
            store.close()

    def test_trend_normalizes_mixed_units_to_common_display_unit(self) -> None:
        store = self._store()
        try:
            # January reported in A, July reported in mA -- must trend on one unit.
            self._add_session(store, 1, [_reading(42.0, "A", MeasurementType.CURRENT_INRUSH, 1, 0, "current")])
            self._add_session(store, 7, [_reading(51000.0, "mA", MeasurementType.CURRENT_INRUSH, 7, 0, "current")])

            trend = AssetTrendService(store.sessions, store.readings).build_trend("motor-1")
            series = trend.series[0]
            self.assertEqual(series.unit, "A")
            self.assertAlmostEqual(series.points[0].avg_value, 42.0)
            self.assertAlmostEqual(series.points[1].avg_value, 51.0)
        finally:
            store.close()

    def test_trend_separates_measurement_types_and_filters(self) -> None:
        store = self._store()
        try:
            self._add_session(store, 1, [
                _reading(12.0, "V", MeasurementType.VOLTAGE_DC, 1, 0, "voltage"),
                _reading(40.0, "A", MeasurementType.CURRENT_INRUSH, 1, 1, "current"),
            ])
            trend = AssetTrendService(store.sessions, store.readings).build_trend("motor-1")
            contexts = {s.context_id for s in trend.series}
            self.assertEqual(contexts, {"voltage_dc", "current_inrush"})

            filtered = AssetTrendService(store.sessions, store.readings).build_trend(
                "motor-1", measurement_type="current_inrush"
            )
            self.assertEqual([s.context_id for s in filtered.series], ["current_inrush"])
        finally:
            store.close()

    def test_trend_skips_non_numeric_readings(self) -> None:
        store = self._store()
        try:
            self._add_session(store, 1, [
                _reading(None, "A", MeasurementType.CURRENT_INRUSH, 1, 0, "current"),
                _reading(40.0, "A", MeasurementType.CURRENT_INRUSH, 1, 1, "current"),
            ])
            trend = AssetTrendService(store.sessions, store.readings).build_trend("motor-1")
            point = trend.series[0].points[0]
            self.assertEqual(point.reading_count, 1)
            self.assertEqual(point.numeric_count, 1)
            self.assertEqual(point.avg_value, 40.0)
        finally:
            store.close()

    def test_export_asset_trend_csv_row_per_session_per_group(self) -> None:
        import csv

        store = self._store()
        try:
            self._add_session(store, 1, [_reading(40.0, "A", MeasurementType.CURRENT_INRUSH, 1, 0, "current")])
            self._add_session(store, 7, [_reading(51.0, "A", MeasurementType.CURRENT_INRUSH, 7, 0, "current")])
            trend = AssetTrendService(store.sessions, store.readings).build_trend("motor-1")

            out = _tmp_dir() / "trend.csv"
            export_asset_trend_csv(trend, out)
            with out.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["measurement"], "current_inrush")
            self.assertEqual(rows[0]["unit"], "A")
            self.assertEqual(rows[0]["avg"], "40.0")
            self.assertEqual(rows[1]["avg"], "51.0")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
