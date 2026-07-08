from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from uuid import uuid4

from tests.unit._helpers import measurement_payload

from fluke_app import EventBus, SessionConnectionMarkers, SessionRecorder, new_session
from fluke_app.device_manager import ConnectionRetryPolicy, ConnectionStateChanged, DeviceManager
from fluke_app.reconnect_policy import ReconnectPolicy
from fluke_core import ConnectionState
from fluke_ble.adapter import BleDevice
from fluke_protocol import ProfileRegistry
from fluke_protocol.profiles.fluke_376fc import FLUKE_MEAS_UUID, FLUKE_STATUS_UUID, Fluke376FCProfile
from fluke_store import FlukeStore
from fluke_testing import FakeBleAdapter, ReplayFrame, ReplayScenario


def _fluke_device(device_id: str) -> BleDevice:
    return BleDevice(
        id=device_id,
        name="Fluke 376 FC",
        address="AA:BB:CC:DD:EE:20",
        rssi=-44,
        metadata={"advertisement_name": "Fluke 376 FC"},
    )


def _fast_manager(adapter: FakeBleAdapter, *, event_bus: EventBus, auto_reconnect: bool = True) -> DeviceManager:
    return DeviceManager(
        adapter,
        ProfileRegistry([Fluke376FCProfile()]),
        event_bus=event_bus,
        retry_policy=ConnectionRetryPolicy(
            recovery_direct_attempts=3,
            recovery_scan_rounds=1,
            recovery_window_s=2.0,
            stream_start_attempts=1,
        ),
        reconnect_policy=ReconnectPolicy(initial_delay_s=0.0, jitter=0.0),
        auto_reconnect=auto_reconnect,
    )


async def _replay(adapter: FakeBleAdapter, device_id: str, text: str) -> None:
    await ReplayScenario(
        (
            ReplayFrame(FLUKE_STATUS_UUID, bytes([0x17])),
            ReplayFrame(FLUKE_MEAS_UUID, measurement_payload(text, "dc")),
        )
    ).run(adapter, device_id)


class ReconnectSessionContinuityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        self._tmp = tmp_root / uuid4().hex
        self._tmp.mkdir(parents=True, exist_ok=False)
        self._store = FlukeStore(self._tmp / "fluke.db")

    def tearDown(self) -> None:
        self._store.close()

    async def test_session_continues_with_gap_markers_across_reconnect(self) -> None:
        adapter = FakeBleAdapter(devices=[_fluke_device("meter-continuity")])
        bus = EventBus()
        states: list[ConnectionStateChanged] = []
        bus.subscribe(ConnectionStateChanged, states.append)

        manager = _fast_manager(adapter, event_bus=bus)
        recorder = SessionRecorder(self._store.sessions, self._store.readings, self._store.markers)
        markers = SessionConnectionMarkers(recorder)
        manager.subscribe_connection_diagnostics(markers.handle_status)
        manager.subscribe_readings(recorder.on_reading)

        terminal = asyncio.Event()
        manager.subscribe_disconnects(terminal.set)

        await manager.scan(timeout_s=0.05)
        device = await manager.establish_session("meter-continuity")
        self._store.upsert_device(device)
        session = recorder.start(new_session(device_id=device.device_id, title="Long run", profile_id=device.profile_id))

        await _replay(adapter, "meter-continuity", "12.34 V")

        # Force one failed reconnect attempt so the backoff path is exercised.
        adapter.script_connect_failures("meter-continuity", 1)
        await adapter.simulate_unexpected_disconnect("meter-continuity")

        await _wait_until(
            lambda: adapter.is_connected("meter-continuity")
            and ("meter-continuity", FLUKE_MEAS_UUID.lower()) in adapter.subscription_keys
            and manager.latest_connection_diagnostics() is not None
            and manager.latest_connection_diagnostics().phase == "recovered"
        )

        await _replay(adapter, "meter-continuity", "12.50 V")
        ended = recorder.stop()
        await manager.disconnect()

        self.assertFalse(terminal.is_set(), "recovery should not have fired a terminal disconnect")
        self.assertIsNotNone(ended)

        # Same session id kept, both readings appended to it.
        readings = self._store.readings.list_for_session(session.session_id)
        self.assertEqual(len(readings), 2)
        self.assertEqual([r.display_text for r in readings], ["12.34 V", "12.50 V"])

        # Gap markers bracket the drop, in order, on the same session.
        stored_markers = self._store.markers.list_for_session(session.session_id)
        labels = [m.label for m in stored_markers]
        self.assertEqual(labels, ["connection_lost", "connection_restored"])

        # State transitions surfaced on the event bus.
        seen = [change.state for change in states]
        self.assertIn(ConnectionState.RECONNECTING, seen)
        self.assertIn(ConnectionState.CONNECTED, seen)
        reconnecting = [c for c in states if c.state == ConnectionState.RECONNECTING]
        self.assertTrue(any(c.is_recovery for c in reconnecting))
        self.assertTrue(any(c.attempt >= 1 for c in reconnecting))
        # A terminal streaming state should be the last connection state observed.
        self.assertEqual(seen[-1], ConnectionState.IDLE)  # from explicit disconnect at teardown

    async def test_no_gap_marker_and_terminal_disconnect_when_reconnect_disabled(self) -> None:
        adapter = FakeBleAdapter(devices=[_fluke_device("meter-noreconnect")])
        bus = EventBus()
        states: list[ConnectionStateChanged] = []
        bus.subscribe(ConnectionStateChanged, states.append)

        manager = _fast_manager(adapter, event_bus=bus, auto_reconnect=False)
        recorder = SessionRecorder(self._store.sessions, self._store.readings, self._store.markers)
        markers = SessionConnectionMarkers(recorder)
        manager.subscribe_connection_diagnostics(markers.handle_status)
        manager.subscribe_readings(recorder.on_reading)

        terminal = asyncio.Event()
        manager.subscribe_disconnects(terminal.set)

        await manager.scan(timeout_s=0.05)
        device = await manager.establish_session("meter-noreconnect")
        self._store.upsert_device(device)
        session = recorder.start(new_session(device_id=device.device_id, profile_id=device.profile_id))
        await _replay(adapter, "meter-noreconnect", "5.00 V")

        self.assertFalse(manager.auto_reconnect_enabled())
        await adapter.simulate_unexpected_disconnect("meter-noreconnect")
        await _wait_until(terminal.is_set)

        stored_markers = self._store.markers.list_for_session(session.session_id)
        self.assertEqual(stored_markers, [])
        self.assertIn(ConnectionState.DISCONNECTED, [c.state for c in states])
        recorder.stop()


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Condition not met before timeout.")


if __name__ == "__main__":
    unittest.main()
