from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

from tests.unit._helpers import measurement_payload

from apps.desktop.presenters import AppPresenter
from fluke_app import DeviceManager
from fluke_ble.adapter import BleDevice
from fluke_protocol import ProfileRegistry
from fluke_protocol.profiles.fluke_376fc import FLUKE_MEAS_UUID, FLUKE_STATUS_UUID, Fluke376FCProfile
from fluke_store import FlukeStore
from fluke_testing import FakeBleAdapter, ReplayFrame, ReplayScenario


class DesktopPresenterTests(unittest.IsolatedAsyncioTestCase):
    async def test_presenter_drives_scan_connect_log_and_export(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-desktop",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:FF",
                    rssi=-47,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            scanned = await presenter.scan_devices(timeout_s=0.1)
            self.assertEqual(len(scanned), 1)
            self.assertEqual(presenter.discovery_view_model().selected_device_id, "meter-desktop")

            await presenter.connect_device()
            self.assertIn("Connected", presenter.home_view_model().connection_text)
            self.assertEqual(len(presenter.home_view_model().recent_devices), 1)
            self.assertIn("desktop.db", presenter.settings_view_model().database_path_text)

            initial = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x17])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.34 V", "dc")),
                )
            )
            await initial.run(adapter, "meter-desktop")
            self.assertEqual(presenter.live_view_model().main_value, "12.34")

            session_id = presenter.start_logging(title="Desktop Replay")
            logged = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.56 V", "dc")),
                )
            )
            await logged.run(adapter, "meter-desktop")

            self.assertEqual(presenter.session_view_model().reading_count_text, "1 readings")
            self.assertTrue(presenter.live_view_model().is_logging)

            presenter.stop_logging()
            self.assertFalse(presenter.live_view_model().is_logging)

            csv_path = presenter.export_session_csv(tmp / "desktop.csv", session_id=session_id)
            json_path = presenter.export_session_json(tmp / "desktop.json", session_id=session_id)
            self.assertTrue(Path(csv_path).exists())
            self.assertTrue(Path(json_path).exists())
            self.assertIn(session_id, [row.session_id for row in presenter.session_view_model().recent_sessions])

            presenter.set_export_directory(tmp / "exports")
            self.assertIn("exports", presenter.settings_view_model().export_directory_text)

            await presenter.disconnect_device()
            self.assertEqual(presenter.live_view_model().connection_text, "Disconnected")
            await presenter.reconnect_last_device()
            self.assertIn("Connected", presenter.home_view_model().connection_text)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
