from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone

from tests.unit._helpers import measurement_payload

from fluke_app.device_manager import ConnectionRetryPolicy, DeviceManager
from fluke_ble.adapter import BleDevice
from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_protocol import ProfileRegistry
from fluke_protocol.profiles.fluke_376fc import FLUKE_MEAS_UUID, FLUKE_STATUS_UUID, Fluke376FCProfile
from fluke_testing import FakeBleAdapter, ReplayFrame, ReplayScenario


class FakeAdapterStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_manager_streams_replayed_readings(self) -> None:
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-1",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:FF",
                    rssi=-41,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))

        devices = await manager.scan()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].profile_id, "fluke_376fc")
        self.assertEqual(devices[0].family_id, "fluke_clamp_meter")
        self.assertEqual(devices[0].variant_id, "376fc")

        await manager.connect(devices[0].device_id)
        self.assertEqual(manager.active_family_id(), "fluke_clamp_meter")
        self.assertIn("device_logging_config", manager.active_capabilities())
        readings: list = []
        manager.subscribe_readings(readings.append)

        await manager.start_stream()
        self.assertEqual(
            set(adapter.subscription_keys),
            {(devices[0].device_id, FLUKE_MEAS_UUID), (devices[0].device_id, FLUKE_STATUS_UUID)},
        )

        scenario = ReplayScenario(
            (
                ReplayFrame(FLUKE_STATUS_UUID, bytes([0x17])),
                ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.34 V", "dc")),
            )
        )
        await scenario.run(adapter, devices[0].device_id)

        self.assertEqual(len(readings), 1)
        reading = readings[0]
        self.assertAlmostEqual(reading.value or 0.0, 12.34)
        self.assertEqual(reading.unit, "V")
        self.assertEqual(reading.measurement_type, MeasurementType.VOLTAGE_DC)
        self.assertEqual(reading.status, ReadingStatus.OK)
        self.assertEqual(manager.latest_reading(), reading)
        self.assertTrue(adapter.is_connected(devices[0].device_id))

        await manager.disconnect()
        self.assertFalse(adapter.is_connected(devices[0].device_id))

    async def test_replay_scenario_can_drive_unknown_name_with_explicit_profile(self) -> None:
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-2",
                    name="Workshop Sensor",
                    address="11:22:33:44:55:66",
                    rssi=-60,
                    metadata={},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))

        await manager.scan()
        await manager.connect("meter-2", profile_id="fluke_376fc")
        readings: list = []
        manager.subscribe_readings(readings.append)
        await manager.start_stream()

        await adapter.emit("meter-2", FLUKE_MEAS_UUID, measurement_payload("OL mV", "dc"))

        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0].measurement_type, MeasurementType.VOLTAGE_DC)
        self.assertEqual(readings[0].status, ReadingStatus.OVER_RANGE)

    async def test_device_manager_can_reconnect_last_device(self) -> None:
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-3",
                    name="Fluke 376 FC",
                    address="22:33:44:55:66:77",
                    rssi=-52,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))

        await manager.scan()
        await manager.connect("meter-3")
        await manager.disconnect()

        self.assertEqual(manager.last_device_id(), "meter-3")

        device = await manager.reconnect()
        self.assertEqual(device.device_id, "meter-3")
        self.assertTrue(adapter.is_connected("meter-3"))

    async def test_establish_session_retries_direct_connect_failures(self) -> None:
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-retry",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:10",
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        adapter.connect_failures_remaining["meter-retry"] = 2
        manager = DeviceManager(
            adapter,
            ProfileRegistry([Fluke376FCProfile()]),
            retry_policy=ConnectionRetryPolicy(
                initial_connect_attempts=3,
                connect_backoff_s=(0.0, 0.0),
                stream_start_attempts=1,
            ),
        )

        await manager.scan(timeout_s=0.1)
        device = await manager.establish_session("meter-retry")

        self.assertEqual(device.device_id, "meter-retry")
        self.assertTrue(adapter.is_connected("meter-retry"))
        self.assertEqual(manager.state(), manager.state().STREAMING)

    async def test_establish_session_can_recover_via_rescan(self) -> None:
        candidate = BleDevice(
            id="meter-rescan",
            name="Fluke 376 FC",
            address="AA:BB:CC:DD:EE:11",
            metadata={"advertisement_name": "Fluke 376 FC", "service_uuids": ["b6981800-7562-11e2-b50d-00163e46f8fe"]},
        )
        adapter = FakeBleAdapter(devices=[], scan_batches=[[], [candidate, candidate]])
        adapter.connect_failures_remaining["meter-rescan"] = 2
        manager = DeviceManager(
            adapter,
            ProfileRegistry([Fluke376FCProfile()]),
            retry_policy=ConnectionRetryPolicy(
                initial_connect_attempts=2,
                connect_backoff_s=(0.0,),
                rescan_rounds=1,
                rescan_passes=2,
                rescan_timeout_s=0.05,
                rescan_connect_attempts=1,
                stream_start_attempts=1,
            ),
        )

        device = await manager.establish_session("meter-rescan")

        self.assertEqual(device.device_id, "meter-rescan")
        self.assertTrue(adapter.is_connected("meter-rescan"))

    async def test_scan_aggregation_merges_duplicate_advertisements(self) -> None:
        adapter = FakeBleAdapter(
            devices=[],
            scan_batches=[
                [
                    BleDevice(
                        id="meter-agg",
                        name="Fluke 376 FC",
                        address="AA:BB:CC:DD:EE:12",
                        rssi=-61,
                        metadata={"advertisement_name": "Fluke 376 FC", "service_uuids": ["1111"]},
                    )
                ],
                [
                    BleDevice(
                        id="meter-agg",
                        name="Fluke 376 FC",
                        address="AA:BB:CC:DD:EE:12",
                        rssi=-48,
                        metadata={"advertisement_name": "Fluke 376 FC", "service_uuids": ["2222"]},
                    )
                ],
            ],
        )
        manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))

        devices = await manager.scan(timeout_s=0.1)

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].rssi, -48)
        self.assertEqual(devices[0].metadata["scan_seen_count"], 2)
        self.assertEqual(devices[0].metadata["service_uuids"], ["1111", "2222"])
        self.assertIn("last_seen_at", devices[0].metadata)

    async def test_establish_session_retries_stream_start(self) -> None:
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-stream-retry",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:13",
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        adapter.subscribe_failures_remaining[("meter-stream-retry", FLUKE_MEAS_UUID.lower())] = 1
        manager = DeviceManager(
            adapter,
            ProfileRegistry([Fluke376FCProfile()]),
            retry_policy=ConnectionRetryPolicy(
                initial_connect_attempts=1,
                stream_start_attempts=2,
            ),
        )

        await manager.scan(timeout_s=0.1)
        await manager.establish_session("meter-stream-retry")

        self.assertTrue(adapter.is_connected("meter-stream-retry"))
        self.assertEqual(
            set(adapter.subscription_keys),
            {("meter-stream-retry", FLUKE_MEAS_UUID.lower()), ("meter-stream-retry", FLUKE_STATUS_UUID.lower())},
        )

    async def test_established_session_auto_recovers_after_unexpected_disconnect(self) -> None:
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-auto-recover",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:14",
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
                recovery_window_s=2.0,
            ),
        )
        readings: list = []
        terminal_disconnect = asyncio.Event()
        manager.subscribe_readings(readings.append)
        manager.subscribe_disconnects(lambda: terminal_disconnect.set())

        await manager.scan(timeout_s=0.1)
        await manager.establish_session("meter-auto-recover")

        first = ReplayScenario(
            (
                ReplayFrame(FLUKE_STATUS_UUID, bytes([0x17])),
                ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.34 V", "dc")),
            )
        )
        await first.run(adapter, "meter-auto-recover")

        await adapter.simulate_unexpected_disconnect("meter-auto-recover")
        await _wait_until(
            lambda: adapter.is_connected("meter-auto-recover")
            and ("meter-auto-recover", FLUKE_MEAS_UUID.lower()) in adapter.subscription_keys
            and manager.latest_connection_diagnostics() is not None
            and manager.latest_connection_diagnostics().phase == "recovered"
        )

        second = ReplayScenario(
            (
                ReplayFrame(FLUKE_STATUS_UUID, bytes([0x17])),
                ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.50 V", "dc")),
            )
        )
        await second.run(adapter, "meter-auto-recover")

        self.assertFalse(terminal_disconnect.is_set())
        self.assertEqual(len(readings), 2)
        self.assertEqual(manager.latest_connection_diagnostics().phase, "recovered")


async def _wait_until(predicate, timeout: float = 0.5) -> None:
    loop = __import__("asyncio").get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await __import__("asyncio").sleep(0.01)
    raise AssertionError("Condition not met before timeout.")


if __name__ == "__main__":
    unittest.main()
