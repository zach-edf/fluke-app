from __future__ import annotations

import asyncio
import unittest

from tests.unit._helpers import measurement_payload

from fluke_app import ConnectionRetryPolicy
from fluke_ble.adapter import BleDevice
from fluke_protocol.profiles.fluke_376fc import FLUKE_MEAS_UUID, FLUKE_STATUS_UUID
from fluke_sdk import FlukeClient
from fluke_testing import FakeBleAdapter, ReplayFrame, ReplayScenario


class FlukeSdkClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_scans_connects_and_streams(self) -> None:
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="sdk-meter",
                    name="Fluke 376 FC",
                    address="99:88:77:66:55:44",
                    rssi=-40,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        client = FlukeClient(ble_adapter=adapter)

        devices = await client.scan(timeout_s=0.1)
        self.assertEqual(len(devices), 1)

        await client.connect(devices[0].device_id)

        async def consume_one():
            async for reading in client.stream_readings():
                return reading
            return None

        consumer = asyncio.create_task(consume_one())
        await asyncio.sleep(0)

        scenario = ReplayScenario(
            (
                ReplayFrame(FLUKE_STATUS_UUID, bytes([0x17])),
                ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.34 V", "dc")),
            )
        )
        await scenario.run(adapter, "sdk-meter")

        reading = await consumer
        self.assertIsNotNone(reading)
        self.assertEqual(reading.display_text, "12.34 V")
        self.assertEqual(client.latest_reading().display_text, "12.34 V")

        await client.disconnect()

    async def test_client_stream_pauses_and_resumes_across_recovery(self) -> None:
        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="sdk-recover",
                    name="Fluke 376 FC",
                    address="99:88:77:66:55:45",
                    rssi=-40,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        client = FlukeClient(
            ble_adapter=adapter,
            retry_policy=ConnectionRetryPolicy(
                recovery_direct_attempts=2,
                recovery_backoff_s=(0.0, 0.0),
                recovery_window_s=2.0,
            ),
        )

        await client.scan(timeout_s=0.1)
        await client.connect("sdk-recover")

        received: list = []

        async def consume_two():
            async for reading in client.stream_readings():
                received.append(reading)
                if len(received) >= 2:
                    break

        consumer = asyncio.create_task(consume_two())
        await asyncio.sleep(0)

        await ReplayScenario(
            (
                ReplayFrame(FLUKE_STATUS_UUID, bytes([0x17])),
                ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.34 V", "dc")),
            )
        ).run(adapter, "sdk-recover")

        await adapter.simulate_unexpected_disconnect("sdk-recover")
        await _wait_until(
            lambda: adapter.is_connected("sdk-recover")
            and ("sdk-recover", FLUKE_MEAS_UUID.lower()) in adapter.subscription_keys
        )

        await ReplayScenario(
            (
                ReplayFrame(FLUKE_STATUS_UUID, bytes([0x17])),
                ReplayFrame(FLUKE_MEAS_UUID, measurement_payload("12.50 V", "dc")),
            )
        ).run(adapter, "sdk-recover")

        await consumer
        self.assertEqual(len(received), 2)
        self.assertIsNone(client.last_connection_error())
        await client.disconnect()


async def _wait_until(predicate, timeout: float = 0.5) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Condition not met before timeout.")


if __name__ == "__main__":
    unittest.main()
