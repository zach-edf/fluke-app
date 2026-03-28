from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


BleNotificationCallback = Callable[[bytes], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class BleDevice:
    id: str
    name: str | None
    address: str
    rssi: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BleCharacteristicInfo:
    uuid: str
    properties: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BleServiceInfo:
    uuid: str
    description: str | None
    characteristics: tuple[BleCharacteristicInfo, ...]


class BleAdapter(Protocol):
    async def scan(self, timeout_s: float = 5.0) -> list[BleDevice]:
        ...

    async def connect(self, device_id: str) -> None:
        ...

    async def disconnect(self, device_id: str) -> None:
        ...

    async def subscribe(
        self,
        device_id: str,
        characteristic_uuid: str,
        callback: BleNotificationCallback,
    ) -> None:
        ...

    async def unsubscribe(self, device_id: str, characteristic_uuid: str) -> None:
        ...

    async def read(self, device_id: str, characteristic_uuid: str) -> bytes:
        ...

    async def write(self, device_id: str, characteristic_uuid: str, data: bytes) -> None:
        ...

    async def services(self, device_id: str) -> list[BleServiceInfo]:
        ...
