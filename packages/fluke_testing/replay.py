from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fluke_testing.fake_ble_adapter import FakeBleAdapter


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    characteristic_uuid: str
    payload: bytes
    delay_s: float = 0.0


@dataclass(frozen=True, slots=True)
class ReplayScenario:
    frames: tuple[ReplayFrame, ...]

    async def run(self, adapter: FakeBleAdapter, device_id: str) -> None:
        for frame in self.frames:
            if frame.delay_s > 0:
                await asyncio.sleep(frame.delay_s)
            await adapter.emit(device_id, frame.characteristic_uuid, frame.payload)
