from __future__ import annotations

import asyncio
import json
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


class HangingSubscribeAdapter(FakeBleAdapter):
    async def subscribe(self, device_id: str, characteristic_uuid: str, callback) -> None:  # type: ignore[override]
        self._require_connected(device_id)
        await asyncio.Event().wait()


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
            self.assertEqual(len(presenter.live_view_model().chart_points), 1)

            session_id = presenter.start_logging(title="Desktop Replay")
            logged = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.56 V", "dc")),
                )
            )
            await logged.run(adapter, "meter-desktop")
            presenter.add_marker("Clamp shifted")

            self.assertEqual(presenter.session_view_model().reading_count_text, "1 readings")
            self.assertTrue(presenter.live_view_model().is_logging)
            self.assertEqual(presenter.live_view_model().marker_count_text, "1 markers")
            self.assertIn("Samples 2", presenter.live_view_model().summary_text)
            self.assertEqual(len(presenter.session_view_model().selected_markers), 1)
            self.assertEqual(len(presenter.session_view_model().chart_points), 1)
            self.assertEqual(presenter.session_view_model().selected_unit_text, "V")

            presenter.stop_logging()
            self.assertFalse(presenter.live_view_model().is_logging)

            csv_path = presenter.export_session_csv(tmp / "desktop.csv", session_id=session_id)
            json_path = presenter.export_session_json(tmp / "desktop.json", session_id=session_id)
            self.assertTrue(Path(csv_path).exists())
            self.assertTrue(Path(json_path).exists())
            payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["statistics"]["reading_count"], 1)
            self.assertEqual(len(payload["markers"]), 1)
            self.assertIn(session_id, [row.session_id for row in presenter.session_view_model().recent_sessions])

            presenter.set_export_directory(tmp / "exports")
            self.assertIn("exports", presenter.settings_view_model().export_directory_text)

            await presenter.disconnect_device()
            self.assertEqual(presenter.live_view_model().connection_text, "Disconnected")
            await presenter.reconnect_last_device()
            self.assertIn("Connected", presenter.home_view_model().connection_text)
        finally:
            store.close()

    async def test_presenter_runs_guided_workflow_against_live_readings(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-workflow.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-workflow",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:FF",
                    rssi=-49,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-workflow")

            presenter.select_workflow("battery_pack_check_v1")
            run_id = presenter.start_workflow()
            self.assertTrue(presenter.live_view_model().is_logging)
            self.assertTrue(presenter.workflow_view_model().is_running)

            presenter.complete_workflow_step(note="Meter configured.")
            self.assertEqual(presenter.workflow_view_model().progress_text, "1/4 steps")

            reading_1 = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("19.80 V", "dc")),
                )
            )
            await reading_1.run(adapter, "meter-workflow")
            presenter.complete_workflow_step(note="Open-circuit reading.")

            reading_2 = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("18.95 V", "dc")),
                )
            )
            await reading_2.run(adapter, "meter-workflow")
            presenter.complete_workflow_step(note="Loaded reading.")
            presenter.complete_workflow_step(note="Voltage sag is acceptable.")

            workflow_vm = presenter.workflow_view_model()
            self.assertFalse(workflow_vm.is_running)
            self.assertIn("Completed Battery Pack Check", workflow_vm.status_text)
            self.assertEqual(len(workflow_vm.completed_steps), 4)
            self.assertEqual(workflow_vm.recent_runs[0].run_id, run_id)
            self.assertEqual(workflow_vm.recent_runs[0].result_text, "Completed")
            self.assertFalse(presenter.live_view_model().is_logging)
            self.assertGreaterEqual(len(store.markers.list_for_session(store.workflow_runs.get(run_id).session_id)), 5)
        finally:
            store.close()

    async def test_presenter_reports_stream_start_timeout_and_disconnects(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-timeout.db")
        adapter = HangingSubscribeAdapter(
            devices=[
                BleDevice(
                    id="meter-timeout",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:11",
                    rssi=-51,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store, device_operation_timeout_s=0.01)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            with self.assertRaisesRegex(RuntimeError, "live stream startup timed out"):
                await presenter.connect_device("meter-timeout")

            self.assertFalse(adapter.is_connected("meter-timeout"))
            self.assertEqual(presenter.live_view_model().connection_text, "Disconnected")
            self.assertEqual(presenter.live_view_model().status_text, "Disconnected")
            self.assertIn("timed out", presenter.discovery_view_model().status_text)
            self.assertIn("timed out", presenter.settings_view_model().diagnostics_text)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
