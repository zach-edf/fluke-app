from __future__ import annotations

import asyncio
from pathlib import Path
import unittest
from uuid import uuid4

from tests.unit._helpers import measurement_payload

from fluke_ble.adapter import BleDevice
from fluke_plugins import build_profile_registry
from fluke_protocol.profiles.fluke_376fc import FLUKE_MEAS_UUID, FLUKE_STATUS_UUID
from fluke_testing import FakeBleAdapter, capture_fixture


class FixtureCaptureToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_fixture_collects_raw_frames(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        adapter = FakeBleAdapter(
            devices=[
                BleDevice(
                    id="meter-1",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:FF",
                    rssi=-40,
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        capture_task = asyncio.create_task(
            capture_fixture(
                adapter,
                build_profile_registry(),
                device_id="meter-1",
                profile_id="fluke_376fc",
                duration_s=1.0,
                max_frames=2,
            )
        )

        await asyncio.sleep(0.05)
        await adapter.emit("meter-1", FLUKE_STATUS_UUID, bytes([0x18]))
        await adapter.emit("meter-1", FLUKE_MEAS_UUID, measurement_payload("12.34 V", "dc"))

        fixture = await capture_task
        exported = Path(fixture.export_json(tmp / "fixture.json"))

        self.assertEqual(len(fixture.frames), 2)
        self.assertEqual(fixture.frames[0].characteristic_uuid.lower(), FLUKE_STATUS_UUID.lower())
        self.assertTrue(exported.exists())
        self.assertIn("0031322e33342056202020006463202020", exported.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
