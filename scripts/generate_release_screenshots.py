from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
for path in (ROOT, PACKAGES):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from apps.desktop._qt import QApplication
from apps.desktop.app import _normalize_application_font
from apps.desktop.runtime import build_runtime
from apps.desktop.theme import STYLESHEET
from apps.desktop.views import create_main_window
from fluke_ble.adapter import BleDevice
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
)
from fluke_testing import FakeBleAdapter, FakeBleService


WINDOW_SIZE = (1500, 1120)


def measurement_payload(primary: str, mode: str) -> bytes:
    display = primary.ljust(10)[:10].encode("ascii")
    mode_bytes = mode.ljust(5)[:5].encode("ascii")
    return b"\x00" + display + b"\x00" + mode_bytes


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


def _prepare_app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    _normalize_application_font(app)
    app.setStyleSheet(STYLESHEET)
    return app


def _set_fluke_theme(window) -> None:
    combo = window._settings.refs["theme_combo"]
    index = combo.findData("fluke")
    if index >= 0:
        combo.setCurrentIndex(index)


def _refresh(window, app: QApplication, cycles: int = 4) -> None:
    for _ in range(cycles):
        window._refresh()
        app.processEvents()


def _save_window(window, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(path), "PNG"):
        raise RuntimeError(f"Failed to save screenshot to {path}")


def _build_runtime_with_store(adapter, db_name: str):
    tmp_root = ROOT / ".test-tmp" / "release-screenshots"
    tmp_root.mkdir(parents=True, exist_ok=True)
    return build_runtime(ble_adapter=adapter, store_path=tmp_root / db_name)


def _show_window(runtime, app: QApplication):
    window = create_main_window(runtime)
    window.resize(*WINDOW_SIZE)
    window.show()
    _set_fluke_theme(window)
    _refresh(window, app, cycles=6)
    return window


def _capture_discovery_and_home(app: QApplication, output_dir: Path) -> None:
    adapter = FakeBleAdapter(
        devices=[
            BleDevice(id="u1", name="Unknown Device", address="00:00:00:00:00:01", rssi=-88, metadata={}),
            BleDevice(id="u2", name="Unknown Device", address="00:00:00:00:00:02", rssi=-71, metadata={}),
            BleDevice(
                id="meter-discovery",
                name="Fluke 376 FC",
                address="AA:BB:CC:DD:EE:10",
                rssi=-49,
                metadata={"advertisement_name": "Fluke 376 FC"},
            ),
            BleDevice(id="u3", name="Unknown Device", address="00:00:00:00:00:03", rssi=-79, metadata={}),
        ]
    )
    runtime = _build_runtime_with_store(adapter, "readme-discovery.db")
    window = _show_window(runtime, app)
    try:
        runtime.runner.wait(runtime.submit(runtime.presenter.scan_devices(timeout_s=0.1)), timeout=10)
        runtime.runner.wait(runtime.submit(runtime.presenter.connect_device("meter-discovery")), timeout=10)
        window._tabs.setCurrentIndex(1)
        _refresh(window, app, cycles=8)
        _save_window(window, output_dir / "readme-device-discovery-connected.png")
        _save_window(window, output_dir / "desktop-device-discovery-connected.png")

        window._tabs.setCurrentIndex(0)
        _refresh(window, app, cycles=6)
        _save_window(window, output_dir / "desktop-home-overview.png")
    finally:
        window.close()
        app.processEvents()
        runtime.close()


def _emit_standard_series(runtime, adapter: FakeBleAdapter, device_id: str, values: list[str]) -> None:
    for value in values:
        runtime.runner.wait(runtime.submit(adapter.emit(device_id, FLUKE_STATUS_UUID, bytes([0x17]))), timeout=10)
        runtime.runner.wait(runtime.submit(adapter.emit(device_id, FLUKE_MEAS_UUID, measurement_payload(value, "dc"))), timeout=10)


def _capture_standard_live_and_workflow(app: QApplication, output_dir: Path) -> None:
    adapter = FakeBleAdapter(
        devices=[
            BleDevice(
                id="meter-live",
                name="Fluke 376 FC",
                address="AA:BB:CC:DD:EE:20",
                rssi=-43,
                metadata={"advertisement_name": "Fluke 376 FC"},
            )
        ]
    )
    runtime = _build_runtime_with_store(adapter, "readme-live.db")
    window = _show_window(runtime, app)
    try:
        runtime.runner.wait(runtime.submit(runtime.presenter.scan_devices(timeout_s=0.1)), timeout=10)
        runtime.runner.wait(runtime.submit(runtime.presenter.connect_device("meter-live")), timeout=10)

        live_refs = window._live.refs
        live_refs["title_input"].setText("Bench Capture")
        live_refs["chart_mode"].setCurrentIndex(live_refs["chart_mode"].findData("rolling_60s"))
        _emit_standard_series(runtime, adapter, "meter-live", ["0.12 A", "0.28 A", "0.41 A", "0.35 A", "0.44 A"])

        window._tabs.setCurrentIndex(2)
        _refresh(window, app, cycles=8)
        _save_window(window, output_dir / "readme-live-reading-logging-settings.png")
        _save_window(window, output_dir / "desktop-live-reading-standard.png")

        workflows = runtime.presenter.workflow_view_model().workflows
        if not workflows:
            raise RuntimeError("No workflows available for screenshot generation.")
        workflow_id = workflows[0].workflow_id
        runtime.presenter.select_workflow(workflow_id)
        _emit_standard_series(runtime, adapter, "meter-live", ["12.20 V", "12.25 V", "12.30 V"])
        runtime.presenter.start_workflow(workflow_id)
        runtime.presenter.complete_workflow_step("Voltage captured for release screenshot.")

        window._tabs.setCurrentIndex(4)
        _refresh(window, app, cycles=8)
        _save_window(window, output_dir / "readme-workflows.png")
        _save_window(window, output_dir / "desktop-workflows-runner.png")
    finally:
        window.close()
        app.processEvents()
        runtime.close()


def _capture_session_replay(app: QApplication, output_dir: Path) -> None:
    adapter = FakeBleAdapter(
        devices=[
            BleDevice(
                id="meter-session",
                name="Fluke 376 FC",
                address="AA:BB:CC:DD:EE:30",
                rssi=-42,
                metadata={"advertisement_name": "Fluke 376 FC"},
            )
        ]
    )
    runtime = _build_runtime_with_store(adapter, "desktop-session.db")
    window = _show_window(runtime, app)
    try:
        runtime.runner.wait(runtime.submit(runtime.presenter.scan_devices(timeout_s=0.1)), timeout=10)
        runtime.runner.wait(runtime.submit(runtime.presenter.connect_device("meter-session")), timeout=10)
        runtime.presenter.start_logging(title="Panel Capture", notes="Replay session for release screenshots.")
        _emit_standard_series(runtime, adapter, "meter-session", ["0.10 A", "0.45 A", "0.52 A", "0.18 A", "0.11 A"])
        runtime.presenter.add_marker("Peak load observed")
        _emit_standard_series(runtime, adapter, "meter-session", ["0.09 A", "0.07 A", "0.12 A"])
        runtime.presenter.add_marker("Load returned to baseline")
        runtime.presenter.stop_logging()

        recent = runtime.presenter.session_view_model().recent_sessions
        if recent:
            runtime.presenter.select_session(recent[0].session_id)

        window._tabs.setCurrentIndex(3)
        _refresh(window, app, cycles=8)
        _save_window(window, output_dir / "desktop-session-replay.png")
    finally:
        window.close()
        app.processEvents()
        runtime.close()


def _capture_device_memory_and_settings(app: QApplication, output_dir: Path) -> None:
    adapter = LoggingDownloadDesktopAdapter()
    runtime = _build_runtime_with_store(adapter, "readme-memory.db")
    window = _show_window(runtime, app)
    try:
        runtime.runner.wait(runtime.submit(runtime.presenter.scan_devices(timeout_s=0.1)), timeout=10)
        runtime.runner.wait(runtime.submit(runtime.presenter.connect_device("meter-memory")), timeout=10)
        runtime.runner.wait(runtime.submit(runtime.presenter.read_device_logging_config()), timeout=10)
        runtime.runner.wait(runtime.submit(runtime.presenter.browse_device_memory(value_source="average")), timeout=10)
        _emit_standard_series(runtime, adapter, "meter-memory", ["0.20 A", "0.24 A"])

        window._tabs.setCurrentIndex(3)
        _refresh(window, app, cycles=8)
        _save_window(window, output_dir / "readme-session-device-memory.png")
        _save_window(window, output_dir / "desktop-session-device-memory-browser.png")

        fixture_path = ROOT / ".test-tmp" / "release-screenshots" / "fixture-capture.json"
        runtime.presenter.export_raw_fixture_capture(fixture_path)
        window._tabs.setCurrentIndex(5)
        _refresh(window, app, cycles=8)
        _save_window(window, output_dir / "desktop-settings-diagnostics.png")
    finally:
        window.close()
        app.processEvents()
        runtime.close()


def _capture_advanced_live(app: QApplication, output_dir: Path) -> None:
    adapter = FakeBleAdapter(
        devices=[
            BleDevice(
                id="meter-advanced",
                name="Fluke 378 FC",
                address="AA:BB:CC:DD:EE:40",
                rssi=-44,
                metadata={"advertisement_name": "Fluke 378 FC"},
            )
        ]
    )
    runtime = _build_runtime_with_store(adapter, "desktop-advanced.db")
    window = _show_window(runtime, app)
    try:
        runtime.runner.wait(runtime.submit(runtime.presenter.scan_devices(timeout_s=0.1)), timeout=10)
        runtime.runner.wait(runtime.submit(runtime.presenter.connect_device("meter-advanced")), timeout=10)

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
        runtime.runner.wait(runtime.submit(adapter.emit("meter-advanced", FLUKE_MEAS_UUID, payload)), timeout=10)

        window._tabs.setCurrentIndex(2)
        _refresh(window, app, cycles=8)
        _save_window(window, output_dir / "desktop-live-reading-advanced-clamp.png")
    finally:
        window.close()
        app.processEvents()
        runtime.close()


def main() -> int:
    output_dir = ROOT / "docs" / "fluke-app-screenshots"
    app = _prepare_app()
    _capture_discovery_and_home(app, output_dir)
    _capture_standard_live_and_workflow(app, output_dir)
    _capture_session_replay(app, output_dir)
    _capture_device_memory_and_settings(app, output_dir)
    _capture_advanced_live(app, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
