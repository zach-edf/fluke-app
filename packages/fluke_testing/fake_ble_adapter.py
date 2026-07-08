from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any

from fluke_ble.adapter import (
    BleAdapter,
    BleCharacteristicInfo,
    BleDevice,
    BleDisconnectCallback,
    BleNotificationCallback,
    BleServiceInfo,
)


@dataclass(frozen=True, slots=True)
class FakeBleService:
    uuid: str
    description: str | None = None
    characteristics: tuple[BleCharacteristicInfo, ...] = ()


@dataclass(slots=True)
class _Subscription:
    callback: BleNotificationCallback


class FakeBleAdapter(BleAdapter):
    def __init__(
        self,
        devices: list[BleDevice] | None = None,
        services_by_device: dict[str, list[FakeBleService]] | None = None,
        scan_batches: list[list[BleDevice]] | None = None,
    ) -> None:
        self._devices = devices or []
        self._scan_batches = list(scan_batches or [])
        self._services_by_device = services_by_device or {}
        self._connected: set[str] = set()
        self._subscriptions: dict[tuple[str, str], _Subscription] = {}
        self._disconnect_callbacks: dict[str, BleDisconnectCallback] = {}
        self.connect_failures_remaining: dict[str, int] = {}
        self.subscribe_failures_remaining: dict[tuple[str, str], int] = {}
        self.read_log: list[tuple[str, str]] = []
        self.write_log: list[tuple[str, str, bytes, bool | None]] = []

    async def scan(self, timeout_s: float = 5.0) -> list[BleDevice]:
        del timeout_s
        if self._scan_batches:
            batch = self._scan_batches.pop(0)
            return list(batch)
        return list(self._devices)

    async def connect(
        self,
        device_id: str,
        *,
        ble_address: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        del ble_address, timeout_s
        remaining = self.connect_failures_remaining.get(device_id, 0)
        if remaining > 0:
            self.connect_failures_remaining[device_id] = remaining - 1
            raise RuntimeError(f"Simulated connect failure for {device_id}")
        self._connected.add(device_id)

    async def disconnect(self, device_id: str) -> None:
        self._connected.discard(device_id)
        self._subscriptions = {
            key: sub for key, sub in self._subscriptions.items() if key[0] != device_id
        }
        self._disconnect_callbacks.pop(device_id, None)

    async def subscribe(
        self,
        device_id: str,
        characteristic_uuid: str,
        callback: BleNotificationCallback,
    ) -> None:
        self._require_connected(device_id)
        key = (device_id, characteristic_uuid.lower())
        remaining = self.subscribe_failures_remaining.get(key, 0)
        if remaining > 0:
            self.subscribe_failures_remaining[key] = remaining - 1
            raise RuntimeError(f"Simulated subscribe failure for {device_id} {characteristic_uuid}")
        self._subscriptions[key] = _Subscription(callback)

    async def unsubscribe(self, device_id: str, characteristic_uuid: str) -> None:
        self._subscriptions.pop((device_id, characteristic_uuid.lower()), None)

    async def read(self, device_id: str, characteristic_uuid: str) -> bytes:
        self._require_connected(device_id)
        self.read_log.append((device_id, characteristic_uuid))
        return b""

    async def write(
        self,
        device_id: str,
        characteristic_uuid: str,
        data: bytes,
        response: bool | None = None,
    ) -> None:
        self._require_connected(device_id)
        self.write_log.append((device_id, characteristic_uuid, bytes(data), response))

    async def services(self, device_id: str) -> list[BleServiceInfo]:
        self._require_connected(device_id)
        return [
            BleServiceInfo(
                uuid=service.uuid,
                description=service.description,
                characteristics=service.characteristics,
            )
            for service in self._services_by_device.get(device_id, [])
        ]

    async def emit(self, device_id: str, characteristic_uuid: str, payload: bytes) -> None:
        key = (device_id, characteristic_uuid.lower())
        subscription = self._subscriptions.get(key)
        if subscription is None:
            raise RuntimeError(f"No subscription for {device_id!r} {characteristic_uuid!r}")
        result = subscription.callback(bytes(payload))
        if inspect.isawaitable(result):
            await result

    def is_connected(self, device_id: str) -> bool:
        return device_id in self._connected

    @property
    def subscription_keys(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._subscriptions.keys())

    def set_disconnect_callback(
        self,
        device_id: str,
        callback: BleDisconnectCallback | None,
    ) -> None:
        if callback is None:
            self._disconnect_callbacks.pop(device_id, None)
        else:
            self._disconnect_callbacks[device_id] = callback

    def script_connect_failures(self, device_id: str, count: int) -> None:
        """Script the next ``count`` connect attempts for ``device_id`` to fail.

        Useful for driving reconnect backoff: after an unexpected disconnect the
        DeviceManager will hit these failures before eventually succeeding.
        """
        self.connect_failures_remaining[device_id] = max(0, int(count))

    async def simulate_unexpected_disconnect(self, device_id: str) -> None:
        """Simulate the device powering off or going out of range mid-stream."""
        self._connected.discard(device_id)
        self._subscriptions = {
            key: sub for key, sub in self._subscriptions.items() if key[0] != device_id
        }
        cb = self._disconnect_callbacks.get(device_id)
        if cb is not None:
            cb(device_id)

    def _require_connected(self, device_id: str) -> None:
        if device_id not in self._connected:
            raise RuntimeError(f"Device {device_id!r} is not connected.")
