from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import TYPE_CHECKING

from fluke_sdk.bootstrap import ensure_repo_paths

ensure_repo_paths()

from fluke_app.device_manager import ConnectionRetryPolicy, DeviceManager
from fluke_app.reconnect_policy import ReconnectPolicy
from fluke_ble.adapter import BleAdapter
from fluke_core import ConnectionState, DeviceInfo, Reading
from fluke_plugins import build_profile_registry

if TYPE_CHECKING:
    from fluke_protocol.registry import ProfileRegistry


_SENTINEL = object()


class FlukeClient:
    def __init__(
        self,
        ble_adapter: BleAdapter | None = None,
        profile_registry: ProfileRegistry | None = None,
        device_manager: DeviceManager | None = None,
        *,
        auto_reconnect: bool = True,
        retry_policy: ConnectionRetryPolicy | None = None,
        reconnect_policy: ReconnectPolicy | None = None,
    ) -> None:
        self._ble_adapter = ble_adapter or _build_ble_adapter()
        self._profiles = profile_registry or build_profile_registry()
        self._manager = device_manager or DeviceManager(
            self._ble_adapter,
            self._profiles,
            retry_policy=retry_policy,
            reconnect_policy=reconnect_policy,
            auto_reconnect=auto_reconnect,
        )
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._latest: Reading | None = None
        self._stream_started = False
        self._last_connection_error: str | None = None
        self._publisher: object | None = None
        self._manager.subscribe_readings(self._handle_reading)
        self._manager.subscribe_disconnects(self._handle_terminal_disconnect)

    async def scan(self, timeout_s: float = 5.0) -> list[DeviceInfo]:
        return await self._manager.scan(timeout_s=timeout_s)

    async def connect(self, device_id: str, profile_id: str | None = None) -> DeviceInfo:
        self._stream_started = False
        self._queue = asyncio.Queue()
        self._last_connection_error = None
        device = await self._manager.establish_session(device_id, profile_id=profile_id)
        self._stream_started = True
        if self._publisher is not None:
            self._publisher.connect(device.device_id, device=device)  # type: ignore[attr-defined]
        return device

    def attach_publisher(self, publisher: object) -> None:
        """Attach a reading publisher (e.g. ``MqttPublisher``).

        The publisher must expose ``connect(device_id, device=...)``,
        ``publish_reading(reading)``, and ``disconnect()``. It receives every
        reading and its connection lifecycle is tied to the client's.
        """
        self._publisher = publisher
        self._manager.subscribe_readings(publisher.publish_reading)  # type: ignore[attr-defined]

    async def disconnect(self) -> None:
        await self._manager.disconnect()
        if self._publisher is not None:
            try:
                self._publisher.disconnect()  # type: ignore[attr-defined]
            except Exception:
                pass
        await self._queue.put(_SENTINEL)

    def state(self) -> ConnectionState:
        return self._manager.state()

    def latest_reading(self) -> Reading | None:
        return self._latest

    def last_connection_error(self) -> str | None:
        return self._last_connection_error

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

    def _handle_terminal_disconnect(self) -> None:
        status = self._manager.latest_connection_diagnostics()
        self._last_connection_error = None if status is None else (status.last_error_text or status.message)
        self._queue.put_nowait(_SENTINEL)

    async def _ensure_streaming(self) -> None:
        if self._stream_started:
            return
        device_id = self._manager.last_device_id()
        if not device_id:
            raise RuntimeError("Connect to a device before streaming readings.")
        await self._manager.establish_session(device_id)
        self._stream_started = True


def _build_ble_adapter() -> BleAdapter:
    try:
        from fluke_ble.bleak_adapter import BleakAdapter
    except ModuleNotFoundError as exc:
        raise RuntimeError("BLE support requires the `bleak` package.") from exc
    return BleakAdapter()
