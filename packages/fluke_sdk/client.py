from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import suppress

from fluke_sdk.bootstrap import ensure_repo_paths

ensure_repo_paths()

from fluke_app.device_manager import DeviceManager
from fluke_ble.adapter import BleAdapter
from fluke_core import ConnectionState, DeviceInfo, Reading
from fluke_protocol import ProfileRegistry
from fluke_protocol.profiles.fluke_376fc import Fluke376FCProfile


_SENTINEL = object()


class FlukeClient:
    def __init__(
        self,
        ble_adapter: BleAdapter | None = None,
        profile_registry: ProfileRegistry | None = None,
        device_manager: DeviceManager | None = None,
    ) -> None:
        self._ble_adapter = ble_adapter or _build_ble_adapter()
        self._profiles = profile_registry or ProfileRegistry([Fluke376FCProfile()])
        self._manager = device_manager or DeviceManager(self._ble_adapter, self._profiles)
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._latest: Reading | None = None
        self._stream_started = False
        self._manager.subscribe_readings(self._handle_reading)

    async def scan(self, timeout_s: float = 5.0) -> list[DeviceInfo]:
        return await self._manager.scan(timeout_s=timeout_s)

    async def connect(self, device_id: str, profile_id: str | None = None) -> DeviceInfo:
        self._stream_started = False
        self._queue = asyncio.Queue()
        return await self._manager.connect(device_id, profile_id=profile_id)

    async def disconnect(self) -> None:
        await self._manager.disconnect()
        await self._queue.put(_SENTINEL)

    def state(self) -> ConnectionState:
        return self._manager.state()

    def latest_reading(self) -> Reading | None:
        return self._latest

    def on_reading(self, handler: Callable[[Reading], None]) -> None:
        self._manager.subscribe_readings(handler)

    async def stream_readings(self) -> AsyncIterator[Reading]:
        await self._ensure_streaming()
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                break
            yield item  # type: ignore[misc]

    async def close(self) -> None:
        with suppress(Exception):
            await self.disconnect()

    def _handle_reading(self, reading: Reading) -> None:
        self._latest = reading
        self._queue.put_nowait(reading)

    async def _ensure_streaming(self) -> None:
        if self._stream_started:
            return
        await self._manager.start_stream()
        self._stream_started = True


def _build_ble_adapter() -> BleAdapter:
    try:
        from fluke_ble.bleak_adapter import BleakAdapter
    except ModuleNotFoundError as exc:
        raise RuntimeError("BLE support requires the `bleak` package.") from exc
    return BleakAdapter()
