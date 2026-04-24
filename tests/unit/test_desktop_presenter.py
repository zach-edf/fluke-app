from __future__ import annotations

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from tests.unit._helpers import measurement_payload

from apps.desktop.presenters import AppPresenter
from fluke_app import ConnectionRetryPolicy, DeviceManager
from fluke_app.workflow_catalog import WorkflowCatalog
from fluke_ble.adapter import BleDevice
from fluke_core.enums import MeasurementType, ReadingStatus, WorkflowInteractionMode
from fluke_core.models.reading import Reading
from fluke_core.models.workflow import WorkflowCaptureSettings, WorkflowDefinition, WorkflowStep
from fluke_protocol import ProfileRegistry
from fluke_protocol.profiles.fluke_376fc import (
    FLUKE_LOGGING_BUFFER_UUID,
    FLUKE_LOGGING_CAPACITY_UUID,
    FLUKE_LOGGING_CONFIG_UUID,
    FLUKE_LOGGING_CONTROL_POINT_UUID,
    FLUKE_LOGGING_SERVICE_UUID,
    FLUKE_LOGGING_STATUS_UUID,
    FLUKE_MEAS_UUID,
    FLUKE_STATUS_UUID,
    Fluke376FCLoggingStatus,
    Fluke376FCProfile,
    FlukeAdvancedClampFamilyProfile,
    FlukeClampMeterFamilyProfile,
)
from fluke_store import FlukeStore
from fluke_testing import FakeBleAdapter, FakeBleService, ReplayFrame, ReplayScenario


class HangingSubscribeAdapter(FakeBleAdapter):
    async def subscribe(self, device_id: str, characteristic_uuid: str, callback) -> None:  # type: ignore[override]
        self._require_connected(device_id)
        await asyncio.Event().wait()


class FailingReconnectAdapter(FakeBleAdapter):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fail_connect_for: set[str] = set()

    async def connect(
        self,
        device_id: str,
        *,
        ble_address: str | None = None,
        timeout_s: float | None = None,
    ) -> None:  # type: ignore[override]
        del ble_address, timeout_s
        if device_id in self.fail_connect_for:
            raise RuntimeError(f"Simulated reconnect failure for {device_id}")
        await super().connect(device_id)


class DelayedReconnectAdapter(FakeBleAdapter):
    def __init__(self, *args, reconnect_delay_s: float = 0.03, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.delayed_connect_for: set[str] = set()
        self._reconnect_delay_s = reconnect_delay_s

    async def connect(
        self,
        device_id: str,
        *,
        ble_address: str | None = None,
        timeout_s: float | None = None,
    ) -> None:  # type: ignore[override]
        del ble_address, timeout_s
        if device_id in self.delayed_connect_for:
            await asyncio.sleep(self._reconnect_delay_s)
        await super().connect(device_id)


class LoggingDownloadDesktopAdapter(FakeBleAdapter):
    def __init__(self) -> None:
        super().__init__(
            devices=[
                BleDevice(
                    id="meter-memory",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:99",
                    rssi=-46,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ],
            services_by_device={
                "meter-memory": [
                    FakeBleService(
                        uuid=FLUKE_LOGGING_SERVICE_UUID,
                        description="Device Logging",
                    )
                ]
            },
        )
        self.status = Fluke376FCLoggingStatus(state_code=0, bytes_logged=36, blocks_logged=2)
        self.capacity = (1024).to_bytes(4, byteorder="little", signed=False)
        self.config_payload = bytes.fromhex("a5 00 00 00 20 1c 00 00")
        self.buffer_chunks = [
            bytes.fromhex("01 04 00 00 a5 00 6b 1c d7 69 99 1c d7 69 12 00 00 00"),
            bytes.fromhex("20 01 01 01 00 00 04 00 fe ff 06 00 00 00 00 00 00 00"),
        ]

    async def read(self, device_id: str, characteristic_uuid: str) -> bytes:  # type: ignore[override]
        await super().read(device_id, characteristic_uuid)
        if characteristic_uuid == FLUKE_LOGGING_STATUS_UUID:
            return self.status.to_payload()
        if characteristic_uuid == FLUKE_LOGGING_CAPACITY_UUID:
            return self.capacity
        if characteristic_uuid == FLUKE_LOGGING_CONFIG_UUID:
            return self.config_payload
        if characteristic_uuid == FLUKE_LOGGING_CONTROL_POINT_UUID:
            return b"\x00"
        return b""

    async def write(
        self,
        device_id: str,
        characteristic_uuid: str,
        data: bytes,
        response: bool | None = None,
    ) -> None:  # type: ignore[override]
        await super().write(device_id, characteristic_uuid, data, response=response)
        if characteristic_uuid == FLUKE_LOGGING_CONFIG_UUID:
            self.config_payload = bytes(data)
            return
        if characteristic_uuid != FLUKE_LOGGING_CONTROL_POINT_UUID:
            return
        if data == b"\x83":
            self.status = Fluke376FCLoggingStatus(state_code=4, bytes_logged=36, blocks_logged=2)
            await self._emit_if_subscribed(device_id, FLUKE_LOGGING_STATUS_UUID, self.status.to_payload())
            return
        if data == b"\x86":
            self.status = Fluke376FCLoggingStatus(state_code=0, bytes_logged=36, blocks_logged=2)
            await self._emit_if_subscribed(device_id, FLUKE_LOGGING_STATUS_UUID, self.status.to_payload())
            return
        if data == b"\x82":
            self.status = Fluke376FCLoggingStatus(state_code=3, bytes_logged=36, blocks_logged=2)
            await self._emit_if_subscribed(device_id, FLUKE_LOGGING_STATUS_UUID, self.status.to_payload())
            self.status = Fluke376FCLoggingStatus(state_code=0, bytes_logged=0, blocks_logged=0)
            await self._emit_if_subscribed(device_id, FLUKE_LOGGING_STATUS_UUID, self.status.to_payload())
            self.buffer_chunks = []
            return
        if len(data) == 9 and data[0] == 0x84:
            start_block = int.from_bytes(data[1:5], byteorder="little", signed=False)
            block_count = int.from_bytes(data[5:9], byteorder="little", signed=False)
            await self._emit_if_subscribed(device_id, FLUKE_LOGGING_CONTROL_POINT_UUID, b"\x02")
            for chunk in self.buffer_chunks[start_block - 1 : start_block - 1 + block_count]:
                await self._emit_if_subscribed(device_id, FLUKE_LOGGING_BUFFER_UUID, chunk)
            await self._emit_if_subscribed(device_id, FLUKE_LOGGING_CONTROL_POINT_UUID, b"\x03")

    async def _emit_if_subscribed(self, device_id: str, characteristic_uuid: str, payload: bytes) -> None:
        if (device_id, characteristic_uuid.lower()) in self.subscription_keys:
            await self.emit(device_id, characteristic_uuid, payload)


async def _wait_until(predicate, timeout: float = 0.5, interval: float = 0.01) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("Condition was not met before timeout.")


def _pack_lsb_fields(widths: tuple[int, ...], values: tuple[int, ...]) -> bytes:
    current = 0
    offset = 0
    for width, value in zip(widths, values, strict=True):
        current |= (value & ((1 << width) - 1)) << offset
        offset += width
    return current.to_bytes((offset + 7) // 8, byteorder="little", signed=False)


def _advanced_clamp_reading_payload(
    *,
    counts: int,
    state: int,
    decimal_places: int,
    magnitude: int,
    sign: int,
    unit_code: int,
    function_code: int,
) -> bytes:
    return _pack_lsb_fields(
        (21, 4, 3, 3, 1, 8, 8, 7, 3, 5, 1),
        (counts, state, decimal_places, magnitude, sign, unit_code, function_code, 0, 0, 0, 0),
    )


def _advanced_clamp_frame(
    primary: bytes,
    secondary: bytes,
    *,
    mode_attrs: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0),
) -> bytes:
    return primary + secondary + _pack_lsb_fields((4, 4, 4, 3, 1), mode_attrs)


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

    async def test_presenter_can_review_and_export_historical_workflow_run_reports(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-workflow-report.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-workflow-report",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:12",
                    rssi=-50,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-workflow-report")
            presenter.select_workflow("battery_pack_check_v1")

            first_run_id = presenter.start_workflow()
            presenter.complete_workflow_step(note="Configured first run.")

            reading_1 = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("19.80 V", "dc")),
                )
            )
            await reading_1.run(adapter, "meter-workflow-report")
            presenter.complete_workflow_step(note="Captured open-circuit voltage.")

            reading_2 = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("18.95 V", "dc")),
                )
            )
            await reading_2.run(adapter, "meter-workflow-report")
            presenter.complete_workflow_step(note="Captured loaded voltage.")
            presenter.complete_workflow_step(note="First run passed.")

            second_run_id = presenter.start_workflow()
            presenter.complete_workflow_step(note="Configured second run.")
            presenter.cancel_workflow()

            presenter.select_workflow_run(first_run_id)
            first_vm = presenter.workflow_view_model()
            self.assertEqual(first_vm.selected_run_id, first_run_id)
            self.assertEqual(first_vm.run_result_text, "Completed")
            self.assertIn("Viewing run: Battery Pack Check", first_vm.selected_run_summary_text)
            self.assertIn("Captured open-circuit voltage.", first_vm.report_text)
            self.assertIn("Summary: 2 captured | 2 completed | 0 skipped", first_vm.report_text)

            export_path = presenter.export_workflow_report(tmp / "workflow-report.md", run_id=first_run_id)
            exported_text = Path(export_path).read_text(encoding="utf-8")
            self.assertIn(f"Run ID: {first_run_id}", exported_text)
            self.assertIn("Result: Completed", exported_text)
            self.assertIn("Captured loaded voltage.", exported_text)

            presenter.select_workflow_run(second_run_id)
            second_vm = presenter.workflow_view_model()
            self.assertEqual(second_vm.selected_run_id, second_run_id)
            self.assertEqual(second_vm.run_result_text, "Aborted")
            self.assertIn("Stopped before:", second_vm.current_step_title)
            self.assertIn("Configured second run.", second_vm.report_text)
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
        manager = DeviceManager(
            adapter,
            ProfileRegistry([Fluke376FCProfile()]),
            retry_policy=ConnectionRetryPolicy(
                initial_connect_attempts=1,
                stream_start_attempts=1,
                stream_start_timeout_s=0.01,
            ),
        )
        presenter = AppPresenter(manager, store, device_operation_timeout_s=0.01)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            with self.assertRaisesRegex(RuntimeError, "Failed to start BLE notifications"):
                await presenter.connect_device("meter-timeout")

            self.assertFalse(adapter.is_connected("meter-timeout"))
            self.assertEqual(presenter.live_view_model().connection_text, "Disconnected")
            self.assertEqual(presenter.live_view_model().status_text, "Disconnected")
            self.assertIn("Connection failed", presenter.discovery_view_model().status_text)
            self.assertIn("Failed to start BLE notifications", presenter.settings_view_model().diagnostics_text)
        finally:
            store.close()

    async def test_presenter_auto_reconnects_after_unexpected_disconnect(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-reconnect.db")
        adapter = DelayedReconnectAdapter(
            devices=[
                BleDevice(
                    id="meter-reconnect",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:44",
                    rssi=-46,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(
            adapter,
            ProfileRegistry([Fluke376FCProfile()]),
            retry_policy=ConnectionRetryPolicy(
                recovery_direct_attempts=2,
                recovery_backoff_s=(0.0, 0.0),
                recovery_window_s=1.0,
            ),
        )
        presenter = AppPresenter(
            manager,
            store,
            device_operation_timeout_s=0.05,
            auto_reconnect_attempts=2,
            auto_reconnect_delay_s=0.01,
        )

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-reconnect")
            presenter.start_logging(title="Reconnect Session")

            first = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.10 V", "dc")),
                )
            )
            await first.run(adapter, "meter-reconnect")

            adapter.delayed_connect_for.add("meter-reconnect")
            await adapter.simulate_unexpected_disconnect("meter-reconnect")
            await _wait_until(lambda: "Reconnecting" in presenter.live_view_model().connection_text)
            await _wait_until(
                lambda: adapter.is_connected("meter-reconnect")
                and any(key[0] == "meter-reconnect" for key in adapter.subscription_keys)
            )
            await _wait_until(
                lambda: presenter.live_view_model().connection_health == "streaming"
                and "Connected" in presenter.live_view_model().connection_text
            )

            second = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.25 V", "dc")),
                )
            )
            await second.run(adapter, "meter-reconnect")

            live = presenter.live_view_model()
            session = presenter.session_view_model()
            self.assertTrue(live.is_logging)
            self.assertEqual(live.connection_health, "streaming")
            self.assertIn("Connected", live.connection_text)
            self.assertIn("Connection restored", live.chart_notice_text)
            self.assertEqual(session.reading_count_text, "2 readings")
            self.assertEqual(live.marker_count_text, "2 markers")
        finally:
            await presenter.shutdown()
            store.close()

    async def test_presenter_reports_reconnect_failure_and_stops_logging(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-reconnect-fail.db")
        adapter = FailingReconnectAdapter(
            devices=[
                BleDevice(
                    id="meter-reconnect-fail",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:55",
                    rssi=-45,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(
            adapter,
            ProfileRegistry([Fluke376FCProfile()]),
            retry_policy=ConnectionRetryPolicy(
                recovery_direct_attempts=2,
                recovery_backoff_s=(0.0, 0.0),
                recovery_window_s=0.2,
            ),
        )
        presenter = AppPresenter(
            manager,
            store,
            device_operation_timeout_s=0.02,
            auto_reconnect_attempts=2,
            auto_reconnect_delay_s=0.01,
        )

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-reconnect-fail")
            presenter.start_logging(title="Reconnect Failure Session")

            first = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("11.90 V", "dc")),
                )
            )
            await first.run(adapter, "meter-reconnect-fail")

            adapter.fail_connect_for.add("meter-reconnect-fail")
            await adapter.simulate_unexpected_disconnect("meter-reconnect-fail")
            await _wait_until(lambda: presenter.live_view_model().connection_text == "Reconnect failed", timeout=0.75)

            live = presenter.live_view_model()
            settings = presenter.settings_view_model()
            workflow = presenter.workflow_view_model()
            self.assertFalse(live.is_logging)
            self.assertEqual(live.connection_health, "error")
            self.assertEqual(live.status_text, "Reconnect failed")
            self.assertIn("Automatic reconnect failed", settings.diagnostics_text)
            self.assertIn("Select a workflow", workflow.status_text)
        finally:
            store.close()

    async def test_presenter_marks_live_connection_as_stale_when_readings_stop(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-stale.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-stale",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:66",
                    rssi=-43,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-stale")
            reading = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("10.00 V", "dc")),
                )
            )
            await reading.run(adapter, "meter-stale")

            presenter._last_reading_time = datetime.now(timezone.utc) - timedelta(seconds=6)
            presenter.check_reading_freshness()

            live = presenter.live_view_model()
            home = presenter.home_view_model()
            self.assertEqual(live.connection_health, "stale")
            self.assertEqual(home.connection_health, "stale")
            self.assertIn("No reading received", live.chart_notice_text)
        finally:
            store.close()

    async def test_presenter_arms_and_triggers_desktop_alerts_without_spam(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-alerts.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-alerts",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:88",
                    rssi=-42,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-alerts")
            presenter.start_logging(title="Alerts Session")
            presenter.set_alert_thresholds(low=None, high=10.0)

            first_alert = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("11.0 V", "dc")),
                )
            )
            await first_alert.run(adapter, "meter-alerts")
            first_live = presenter.live_view_model()
            self.assertTrue(first_live.alert_active)
            self.assertEqual(first_live.alert_status_text, "Alerts armed: high > 10.")
            self.assertIn("HIGH ALERT", first_live.alert_message)
            self.assertEqual(first_live.alert_event_id, 1)
            self.assertEqual(first_live.marker_count_text, "1 markers")

            sustained_alert = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("11.4 V", "dc")),
                )
            )
            await sustained_alert.run(adapter, "meter-alerts")
            second_live = presenter.live_view_model()
            self.assertEqual(second_live.alert_event_id, 1)
            self.assertEqual(second_live.marker_count_text, "1 markers")

            recovered = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("9.5 V", "dc")),
                )
            )
            await recovered.run(adapter, "meter-alerts")
            recovered_live = presenter.live_view_model()
            self.assertFalse(recovered_live.alert_active)

            second_excursion = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("10.8 V", "dc")),
                )
            )
            await second_excursion.run(adapter, "meter-alerts")
            final_live = presenter.live_view_model()
            self.assertEqual(final_live.alert_event_id, 2)
            self.assertEqual(final_live.marker_count_text, "2 markers")
        finally:
            store.close()

    async def test_presenter_rejects_invalid_alert_thresholds_without_clearing_existing_config(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-alert-config.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-alert-config",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:99",
                    rssi=-41,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-alert-config")
            presenter.set_alert_thresholds(low=2.0, high=10.0)
            self.assertEqual(
                presenter.live_view_model().alert_status_text,
                "Alerts armed: low < 2, high > 10.",
            )

            presenter.set_alert_thresholds(low=12.0, high=10.0)
            self.assertIn("Alert config error", presenter.live_view_model().alert_status_text)

            reading = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("11.1 V", "dc")),
                )
            )
            await reading.run(adapter, "meter-alert-config")
            live = presenter.live_view_model()
            self.assertTrue(live.alert_active)
            self.assertEqual(live.alert_event_id, 1)
        finally:
            store.close()

    async def test_presenter_resets_live_chart_when_measurement_context_changes(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-context.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-context",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:22",
                    rssi=-48,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-context")

            voltage_reading = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.34 V", "dc")),
                )
            )
            await voltage_reading.run(adapter, "meter-context")
            first_live = presenter.live_view_model()
            self.assertIn("Voltage", first_live.measurement_label)
            self.assertEqual(first_live.unit_text, "V")
            self.assertEqual(len(first_live.chart_points), 1)
            self.assertEqual(first_live.chart_notice_text, "")
            self.assertIn("Samples 1", first_live.summary_text)

            current_reading = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("1.25 A", "ac")),
                )
            )
            await current_reading.run(adapter, "meter-context")
            second_live = presenter.live_view_model()
            self.assertIn("Current", second_live.measurement_label)
            self.assertEqual(second_live.unit_text, "A")
            self.assertEqual(len(second_live.chart_points), 1)
            self.assertIn("chart reset", second_live.chart_notice_text.lower())
            self.assertIn("Current", second_live.chart_notice_text)
            self.assertIn("Samples 1", second_live.summary_text)
        finally:
            store.close()

    async def test_presenter_filters_session_replay_by_cleaned_measurement_context(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-session-filter.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-session-filter",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:33",
                    rssi=-47,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-session-filter")
            session_id = presenter.start_logging(title="Mixed Session")

            resistance_1 = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("1200 ohm", "")),
                )
            )
            await resistance_1.run(adapter, "meter-session-filter")
            presenter.add_marker("Resistance capture 1", label="note")

            resistance_2 = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("1.3 kOhm", "dc")),
                )
            )
            await resistance_2.run(adapter, "meter-session-filter")
            presenter.add_marker("Resistance capture 2", label="note")

            unknown_transition = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("OL", "dc")),
                )
            )
            await unknown_transition.run(adapter, "meter-session-filter")

            voltage_reading = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.34 V", "dc")),
                )
            )
            await voltage_reading.run(adapter, "meter-session-filter")
            presenter.add_marker("Voltage capture", label="note")
            presenter.stop_logging()

            presenter.select_session(session_id)
            full_session = presenter.session_view_model()
            self.assertEqual(len(full_session.available_contexts), 2)
            self.assertEqual([ctx.label for ctx in full_session.available_contexts], ["Resistance", "Voltage DC"])
            self.assertEqual(full_session.selected_context_label, "Resistance")
            self.assertEqual(full_session.selected_unit_text, "kOhm")
            self.assertEqual(len(full_session.chart_points), 2)
            self.assertEqual(len(full_session.selected_markers), 2)
            self.assertIn("Samples 2", full_session.selected_summary_text)

            presenter.select_session_context(None)
            mixed_session = presenter.session_view_model()
            self.assertEqual(mixed_session.selected_context_id, None)
            self.assertEqual(mixed_session.selected_context_label, "All Measurements")
            self.assertEqual(len(mixed_session.chart_points), 0)
            self.assertEqual(len(mixed_session.selected_markers), 3)
            self.assertIn("Mixed measurement session", mixed_session.selected_summary_text)

            voltage_context = next(ctx for ctx in full_session.available_contexts if ctx.label == "Voltage DC")
            presenter.select_session_context(voltage_context.context_id)
            filtered_session = presenter.session_view_model()
            self.assertEqual(filtered_session.selected_context_id, voltage_context.context_id)
            self.assertEqual(filtered_session.selected_context_label, voltage_context.label)
            self.assertEqual(filtered_session.selected_unit_text, "V")
            self.assertEqual(len(filtered_session.chart_points), 1)
            self.assertEqual(len(filtered_session.selected_markers), 1)
            self.assertIn("Samples 1", filtered_session.selected_summary_text)
        finally:
            store.close()

    async def test_presenter_can_compare_sessions_with_shared_measurement_view(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-session-compare.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-session-compare",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:77",
                    rssi=-44,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-session-compare")

            reference_session_id = presenter.start_logging(title="Reference Session")
            reference = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("1.2 kOhm", "")),
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("1.3 kOhm", "")),
                )
            )
            await reference.run(adapter, "meter-session-compare")
            presenter.stop_logging()

            comparison_session_id = presenter.start_logging(title="Comparison Session")
            comparison = ReplayScenario(
                (
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("150 ohm", "")),
                    ReplayFrame(FLUKE_STATUS_UUID, bytes([0x18])),
                    ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("250 ohm", "")),
                )
            )
            await comparison.run(adapter, "meter-session-compare")
            presenter.stop_logging()

            presenter.select_session(reference_session_id)
            presenter.select_compare_session(comparison_session_id)

            session_vm = presenter.session_view_model()
            self.assertEqual(session_vm.selected_context_label, "Resistance")
            self.assertEqual(session_vm.selected_unit_text, "kOhm")
            self.assertEqual(session_vm.compare_session_id, comparison_session_id)
            self.assertEqual(session_vm.compare_session_label, "Comparison Session")
            self.assertEqual(len(session_vm.compare_chart_points), 2)
            self.assertAlmostEqual(session_vm.compare_chart_points[0][1], 0.15, places=3)
            self.assertAlmostEqual(session_vm.compare_chart_points[1][1], 0.25, places=3)
            self.assertIn("Compared with Comparison Session", session_vm.compare_summary_text)
        finally:
            store.close()

    async def test_presenter_can_import_device_memory_into_session_store(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-device-memory.db")
        adapter = LoggingDownloadDesktopAdapter()
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-memory")

            report = await presenter.import_device_memory()

            self.assertEqual(report["import_report"]["imported_count"], 1)
            self.assertEqual(report["download_report"]["downloaded_bytes"], 36)
            session_vm = presenter.session_view_model()
            self.assertEqual(len(session_vm.recent_sessions), 1)
            imported_session_id = session_vm.recent_sessions[0].session_id
            self.assertEqual(session_vm.selected_session_id, imported_session_id)
            self.assertEqual(session_vm.selected_unit_text, "A")
            self.assertIn("Imported 1 device-memory session(s)", session_vm.export_status_text)

            readings = store.readings.list_for_session(imported_session_id)
            self.assertEqual(len(readings), 1)
            self.assertEqual(readings[0].measurement_type, MeasurementType.CURRENT_DC)
            self.assertEqual(readings[0].status, ReadingStatus.OK)
            self.assertEqual(readings[0].metadata["source"], "device_memory")
        finally:
            store.close()

    async def test_presenter_can_browse_import_and_clear_device_memory(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-device-memory-browser.db")
        adapter = LoggingDownloadDesktopAdapter()
        manager = DeviceManager(adapter, ProfileRegistry([FlukeClampMeterFamilyProfile(), Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-memory")

            status_report = await presenter.refresh_device_memory_status()
            self.assertEqual(status_report["bytes_logged"], 36)
            self.assertEqual(status_report["blocks_logged"], 2)

            browse_report = await presenter.browse_device_memory(value_source="maximum")
            self.assertEqual(browse_report["download_report"]["downloaded_bytes"], 36)

            session_vm = presenter.session_view_model()
            self.assertEqual(session_vm.device_memory_value_source, "maximum")
            self.assertEqual(len(session_vm.device_memory_sessions), 1)
            self.assertIn("36 byte(s), 2 block(s)", session_vm.device_memory_status_text)
            self.assertIn("1024 byte(s)", session_vm.device_memory_capacity_text)
            preview_id = session_vm.device_memory_sessions[0].preview_id

            import_report = await presenter.import_selected_device_memory((preview_id,), value_source="maximum")
            self.assertEqual(import_report["import_report"]["imported_count"], 1)
            session_vm_after_import = presenter.session_view_model()
            self.assertEqual(session_vm_after_import.device_memory_sessions[0].import_status_text, "Imported")

            clear_report = await presenter.clear_device_memory()
            self.assertEqual(clear_report["status_after"]["bytes_logged"], 0)
            self.assertEqual(clear_report["status_after"]["blocks_logged"], 0)
            session_vm_after_clear = presenter.session_view_model()
            self.assertEqual(len(session_vm_after_clear.device_memory_sessions), 0)
            self.assertIn("0 byte(s), 0 block(s)", session_vm_after_clear.device_memory_status_text)
        finally:
            store.close()

    async def test_presenter_can_read_and_apply_device_logging_settings(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-device-settings.db")
        adapter = LoggingDownloadDesktopAdapter()
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-memory")

            read_report = await presenter.read_device_logging_config()
            self.assertEqual(read_report["interval_seconds"], 165)
            self.assertEqual(read_report["duration_seconds"], 7200)

            live = presenter.live_view_model()
            self.assertEqual(live.logging_interval_seconds_text, "165")
            self.assertEqual(live.logging_duration_seconds_text, "7200")
            self.assertFalse(live.logging_manual_stop)

            write_report = await presenter.apply_device_logging_config(
                interval_seconds=915,
                duration_seconds=0,
            )
            self.assertTrue(write_report["write_ok"])

            live_after = presenter.live_view_model()
            self.assertEqual(live_after.logging_interval_seconds_text, "915")
            self.assertEqual(live_after.logging_duration_seconds_text, "")
            self.assertTrue(live_after.logging_manual_stop)
            self.assertIn("interval 915s, duration manual", live_after.logging_status_text)
            self.assertEqual(adapter.config_payload.hex(" "), "93 03 00 00 00 00 00 00")
        finally:
            store.close()

    async def test_presenter_surfaces_advanced_clamp_live_channels_and_mode_badges(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-advanced-clamp-live.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-advanced-clamp",
                    name="Fluke 378 FC",
                    address="AA:BB:CC:DD:EE:37",
                    rssi=-45,
                    metadata={"advertisement_name": "Fluke 378 FC"},
                )
            ]
        )
        manager = DeviceManager(
            adapter,
            ProfileRegistry([FlukeAdvancedClampFamilyProfile(), FlukeClampMeterFamilyProfile(), Fluke376FCProfile()]),
        )
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-advanced-clamp")

            payload = _advanced_clamp_frame(
                _advanced_clamp_reading_payload(
                    counts=123,
                    state=0,
                    decimal_places=1,
                    magnitude=0,
                    sign=0,
                    unit_code=2,
                    function_code=12,
                ),
                _advanced_clamp_reading_payload(
                    counts=45,
                    state=0,
                    decimal_places=2,
                    magnitude=0,
                    sign=0,
                    unit_code=4,
                    function_code=21,
                ),
                mode_attrs=(8, 2, 7, 1, 1),
            )
            await adapter.emit("meter-advanced-clamp", FLUKE_MEAS_UUID, payload)

            live = presenter.live_view_model()
            self.assertIn("live_primary_secondary", live.available_capabilities)
            self.assertIn("Primary/Secondary Live", live.capability_summary_text)
            self.assertEqual(live.live_primary_reading, "12.3")
            self.assertEqual(live.live_secondary_reading, "0.45")
            self.assertIn("Clockwise", live.family_mode_badges)

            presenter.select_live_channel("secondary")
            live_secondary = presenter.live_view_model()
            self.assertEqual(live_secondary.selected_live_channel, "secondary")
            self.assertEqual(live_secondary.main_value, "0.45")
        finally:
            store.close()

    async def test_presenter_can_export_raw_fixture_from_live_buffer(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-fixture-export.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-fixture",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:FA",
                    rssi=-47,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([FlukeClampMeterFamilyProfile(), Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store, export_directory=tmp)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-fixture")

            await adapter.emit("meter-fixture", FLUKE_STATUS_UUID, bytes([0x17]))
            await adapter.emit("meter-fixture", FLUKE_MEAS_UUID, measurement_payload("12.34 V", "dc"))

            fixture_path = Path(presenter.export_raw_fixture_capture(tmp / "fixture.json", max_frames=10))
            self.assertTrue(fixture_path.exists())

            payload = json.loads(fixture_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["device"]["device_id"], "meter-fixture")
            self.assertEqual(payload["device"]["family_id"], "fluke_clamp_meter")
            self.assertEqual(payload["frame_count"], 2)
            self.assertEqual(payload["frames"][0]["characteristic_uuid"].lower(), FLUKE_STATUS_UUID.lower())
            self.assertEqual(payload["frames"][1]["characteristic_uuid"].lower(), FLUKE_MEAS_UUID.lower())
            self.assertEqual(payload["parsed_readings"][0]["measurement_type"], MeasurementType.VOLTAGE_DC.value)
            self.assertIn("raw frame(s) buffered", presenter.settings_view_model().live_buffer_text)
        finally:
            store.close()

    async def test_presenter_stable_capture_supports_retake_and_continue(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-stable-capture.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-stable-capture",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:AB",
                    rssi=-47,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        catalog = WorkflowCatalog(
            [
                WorkflowDefinition(
                    workflow_id="stable_capture_only",
                    title="Stable Capture Only",
                    steps=(
                        WorkflowStep(
                            step_id="capture_voltage",
                            title="Capture Voltage",
                            instruction="Hold a steady DC voltage reading.",
                            capture=True,
                            interaction_mode=WorkflowInteractionMode.STABLE_CAPTURE,
                            advance_on_capture=False,
                            capture_settings=WorkflowCaptureSettings(
                                stable_for_s=0.75,
                                min_samples=5,
                                relative_tolerance=0.01,
                            ),
                            expected_measurement_type=MeasurementType.VOLTAGE_DC,
                            expected_unit="V",
                        ),
                    ),
                )
            ]
        )
        presenter = AppPresenter(manager, store, workflow_catalog=catalog)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-stable-capture")
            presenter.select_workflow("stable_capture_only")
            run_id = presenter.start_workflow()

            for offset_ms, value in zip((0, 200, 400, 800, 1000), (12.0, 12.0, 12.01, 12.0, 12.0), strict=True):
                presenter.on_reading(_manual_voltage_reading("meter-stable-capture", value, offset_ms))

            workflow_vm = presenter.workflow_view_model()
            self.assertEqual(workflow_vm.capture_state_text, "Captured")
            self.assertTrue(workflow_vm.can_continue_capture)
            self.assertTrue(workflow_vm.can_retake_capture)
            self.assertIn("Pending capture: 12 V", workflow_vm.latest_capture_text)

            presenter.retake_workflow_capture()
            workflow_vm = presenter.workflow_view_model()
            self.assertEqual(workflow_vm.capture_state_text, "Contact detected")
            self.assertIn("Retake armed", workflow_vm.capture_hint_text)

            for offset_ms, value in zip((1200, 1400, 1600, 2000, 2200), (12.2, 12.2, 12.21, 12.2, 12.2), strict=True):
                presenter.on_reading(_manual_voltage_reading("meter-stable-capture", value, offset_ms))

            presenter.continue_workflow_capture(note="Captured stable bench voltage.")

            workflow_vm = presenter.workflow_view_model()
            self.assertFalse(workflow_vm.is_running)
            self.assertEqual(store.workflow_runs.get(run_id).result.value, "completed")
            results = store.workflow_step_results.list_for_run(run_id)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].reading.display_text, "12.2 V")
        finally:
            store.close()

    async def test_presenter_supports_live_chart_modes_and_session_segment_axis(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "desktop-chart-modes.db")
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-chart-modes",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:AC",
                    rssi=-46,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
        presenter = AppPresenter(manager, store)

        try:
            await presenter.scan_devices(timeout_s=0.1)
            await presenter.connect_device("meter-chart-modes")
            session_id = presenter.start_logging(title="Chart Modes Session")

            for offset_s, value in ((0, 10.0), (1, 10.1), (2, 10.2), (38, 10.3), (39, 10.4)):
                reading = _manual_voltage_reading("meter-chart-modes", value, offset_s * 1000)
                presenter.on_reading(reading)
                presenter._recorder.on_reading(reading)
            presenter.stop_logging()

            live = presenter.live_view_model()
            self.assertEqual(len(live.chart_points), 2)

            presenter.select_live_chart_mode("since_mode_start")
            live = presenter.live_view_model()
            self.assertEqual(live.selected_chart_mode, "since_mode_start")
            self.assertEqual(len(live.chart_points), 0)
            self.assertIn("Since mode start", live.chart_notice_text)

            presenter.select_session(session_id)
            session_vm = presenter.session_view_model()
            self.assertEqual(session_vm.selected_axis_mode, "elapsed")
            self.assertEqual(session_vm.chart_x_mode, "elapsed")

            presenter.select_session_axis_mode("utc")
            session_vm = presenter.session_view_model()
            self.assertEqual(session_vm.chart_x_mode, "datetime")
            self.assertEqual(session_vm.chart_x_title, "UTC")
            self.assertGreater(session_vm.chart_points[0][0], 1_000_000_000_000)

            presenter.select_session_axis_mode("by_segment")
            session_vm = presenter.session_view_model()
            self.assertEqual(len(session_vm.available_segments), 2)
            self.assertEqual(session_vm.selected_segment_id, "segment_1")
            self.assertEqual(session_vm.chart_x_mode, "elapsed")
            self.assertEqual(len(session_vm.chart_points), 3)

            presenter.select_session_segment("segment_2")
            session_vm = presenter.session_view_model()
            self.assertEqual(session_vm.selected_segment_id, "segment_2")
            self.assertEqual(len(session_vm.chart_points), 2)
            self.assertEqual(session_vm.chart_points[0][0], 0.0)
        finally:
            store.close()


def _manual_voltage_reading(device_id: str, value: float, offset_ms: int) -> Reading:
    base = datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc)
    return Reading(
        timestamp_utc=base + timedelta(milliseconds=offset_ms),
        value=value,
        unit="V",
        measurement_type=MeasurementType.VOLTAGE_DC,
        status=ReadingStatus.OK,
        display_text=f"{value:g} V",
        source_device_id=device_id,
        mode="dc",
        metadata={"unit_family": "voltage"},
    )


if __name__ == "__main__":
    unittest.main()
