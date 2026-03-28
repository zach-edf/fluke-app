from __future__ import annotations

import unittest
from datetime import datetime, timezone

from tests.unit._helpers import measurement_payload

from fluke_app.device_manager import DeviceManager
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

        await manager.connect(devices[0].device_id)
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


if __name__ == "__main__":
    unittest.main()
