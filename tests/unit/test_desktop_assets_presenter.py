from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tests.unit._helpers import ROOT  # noqa: F401

from apps.desktop.presenters import AppPresenter
from fluke_app import DeviceManager, new_session
from fluke_ble.adapter import BleDevice
from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_protocol import ProfileRegistry
from fluke_protocol.profiles.fluke_376fc import Fluke376FCProfile
from fluke_store import FlukeStore
from fluke_testing import FakeBleAdapter


def _tmp_dir() -> Path:
    tmp = Path(__file__).resolve().parents[2] / ".test-tmp" / uuid4().hex
    tmp.mkdir(parents=True, exist_ok=False)
    return tmp


class DesktopAssetsPresenterTests(unittest.TestCase):
    def _presenter(self) -> tuple[AppPresenter, FlukeStore]:
        store = FlukeStore(_tmp_dir() / "assets.db")
        store.upsert_device(
            DeviceInfo(device_id="d1", ble_address="AA", model_name="M", profile_id="p", support_level="supported")
        )
        manager = DeviceManager(FakeBleAdapter(devices=[]), ProfileRegistry([Fluke376FCProfile()]))
        return AppPresenter(manager, store), store

    def _add_session(self, store, month, value):
        session = new_session(
            device_id="d1", title=f"run-{month}", asset_id="motor-1",
            started_at=datetime(2026, month, 1, tzinfo=timezone.utc),
        )
        store.sessions.create(session)
        store.readings.append(
            session.session_id,
            Reading(
                timestamp_utc=datetime(2026, month, 1, tzinfo=timezone.utc),
                value=value, unit="A", measurement_type=MeasurementType.CURRENT_INRUSH,
                status=ReadingStatus.OK, display_text=f"{value} A", source_device_id="d1",
                metadata={"unit_family": "current"},
            ),
        )
        return session

    def test_create_and_list_assets(self) -> None:
        presenter, store = self._presenter()
        try:
            asset_id = presenter.create_asset("Line 3 Motor", "motor", "Bay 2", "notes")
            view = presenter.assets_view_model()
            self.assertEqual(len(view.assets), 1)
            self.assertEqual(view.selected_asset_id, asset_id)
            self.assertEqual(view.assets[0].name, "Line 3 Motor")
            self.assertIn((asset_id, "Line 3 Motor"), view.asset_options)
        finally:
            store.close()

    def test_select_asset_builds_trend_points(self) -> None:
        presenter, store = self._presenter()
        try:
            presenter.create_asset("Motor")  # generates its own id
            asset_id = presenter.assets_view_model().selected_asset_id
            # re-point sessions to the created asset id
            self._add_session_for(store, asset_id, 1, 42.0)
            self._add_session_for(store, asset_id, 7, 51.0)

            presenter.select_asset(asset_id)
            view = presenter.assets_view_model()
            self.assertEqual(len(view.linked_sessions), 2)
            self.assertEqual(view.selected_measurement_id, "current_inrush")
            self.assertEqual(view.trend_unit_text, "A")
            # default stat is avg
            ys = [y for _x, y in view.trend_points]
            self.assertEqual(ys, [42.0, 51.0])

            presenter.select_asset_stat("max")
            self.assertIn("max", presenter.assets_view_model().trend_label_text)
        finally:
            store.close()

    def _add_session_for(self, store, asset_id, month, value):
        session = new_session(
            device_id="d1", title=f"run-{month}", asset_id=asset_id,
            started_at=datetime(2026, month, 1, tzinfo=timezone.utc),
        )
        store.sessions.create(session)
        store.readings.append(
            session.session_id,
            Reading(
                timestamp_utc=datetime(2026, month, 1, tzinfo=timezone.utc),
                value=value, unit="A", measurement_type=MeasurementType.CURRENT_INRUSH,
                status=ReadingStatus.OK, display_text=f"{value} A", source_device_id="d1",
                metadata={"unit_family": "current"},
            ),
        )

    def test_assign_session_asset_updates_links(self) -> None:
        presenter, store = self._presenter()
        try:
            asset_id = presenter.create_asset("Motor")
            orphan = new_session(device_id="d1", title="orphan")
            store.sessions.create(orphan)

            presenter.assign_session_asset(orphan.session_id, asset_id)
            self.assertEqual(store.sessions.get(orphan.session_id).asset_id, asset_id)
            presenter.select_asset(asset_id)
            self.assertEqual(len(presenter.assets_view_model().linked_sessions), 1)

            presenter.assign_session_asset(orphan.session_id, None)
            self.assertIsNone(store.sessions.get(orphan.session_id).asset_id)
        finally:
            store.close()

    def test_delete_asset_clears_selection_and_detaches(self) -> None:
        presenter, store = self._presenter()
        try:
            asset_id = presenter.create_asset("Motor")
            self._add_session_for(store, asset_id, 1, 42.0)
            presenter.select_asset(asset_id)

            presenter.delete_asset(asset_id)
            view = presenter.assets_view_model()
            self.assertIsNone(view.selected_asset_id)
            self.assertEqual(len(view.assets), 0)
            # linked session remains but is detached
            remaining = store.sessions.list_recent()
            self.assertTrue(remaining)
            self.assertIsNone(remaining[0].asset_id)
        finally:
            store.close()

    def test_start_logging_rejects_unknown_asset(self) -> None:
        presenter, store = self._presenter()
        try:
            # simulate a connected device by directly seeding the current device
            presenter._current_device = store.devices.get("d1")  # type: ignore[attr-defined]
            with self.assertRaises(RuntimeError):
                presenter.start_logging(title="x", asset_id="does-not-exist")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
