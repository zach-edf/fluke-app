from __future__ import annotations

import asyncio
import inspect
from typing import Any

from bleak import BleakClient, BleakScanner

from fluke_ble.adapter import (
    BleAdapter,
    BleCharacteristicInfo,
    BleDevice,
    BleDisconnectCallback,
    BleNotificationCallback,
    BleServiceInfo,
)


class BleakAdapter(BleAdapter):
    def __init__(self) -> None:
        self._clients: dict[str, BleakClient] = {}
        self._disconnect_callbacks: dict[str, BleDisconnectCallback] = {}
        self._deliberate_disconnect: set[str] = set()

    async def scan(self, timeout_s: float = 5.0) -> list[BleDevice]:
        try:
            discovered = await BleakScanner.discover(timeout=timeout_s, return_adv=True)
        except TypeError:
            devices = await BleakScanner.discover(timeout=timeout_s)
            return [
                BleDevice(
                    id=device.address,
                    name=device.name,
                    address=device.address,
                    rssi=getattr(device, "rssi", None),
                )
                for device in devices
            ]

        matches: list[BleDevice] = []
        for identifier, (device, adv) in discovered.items():
            name = device.name or adv.local_name
            metadata = {
                "advertisement_name": adv.local_name,
                "service_uuids": list(adv.service_uuids or []),
                "manufacturer_data_ids": sorted((adv.manufacturer_data or {}).keys()),
            }
            matches.append(
                BleDevice(
                    id=identifier,
                    name=name,
                    address=device.address or identifier,
                    rssi=adv.rssi,
                    metadata=metadata,
                )
            )
        return matches

    async def connect(self, device_id: str) -> None:
        client = self._clients.get(device_id)
        if client is not None and client.is_connected:
            return

        self._deliberate_disconnect.discard(device_id)

        def _on_disconnected(_client: BleakClient) -> None:
            self._clients.pop(device_id, None)
            if device_id in self._deliberate_disconnect:
                self._deliberate_disconnect.discard(device_id)
                return
            cb = self._disconnect_callbacks.get(device_id)
            if cb is not None:
                cb(device_id)

        client = BleakClient(device_id, disconnected_callback=_on_disconnected)
        await client.connect()
        self._clients[device_id] = client

    async def disconnect(self, device_id: str) -> None:
        self._deliberate_disconnect.add(device_id)
        client = self._clients.pop(device_id, None)
        if client is not None and client.is_connected:
            await client.disconnect()
        self._disconnect_callbacks.pop(device_id, None)

    async def subscribe(
        self,
        device_id: str,
        characteristic_uuid: str,
        callback: BleNotificationCallback,
    ) -> None:
        client = self._require_client(device_id)

        def _handle(_: Any, data: bytearray) -> None:
            result = callback(bytes(data))
            if inspect.isawaitable(result):
                asyncio.create_task(result)

        await client.start_notify(characteristic_uuid, _handle)

    async def unsubscribe(self, device_id: str, characteristic_uuid: str) -> None:
        client = self._require_client(device_id)
        await client.stop_notify(characteristic_uuid)

    async def read(self, device_id: str, characteristic_uuid: str) -> bytes:
        client = self._require_client(device_id)
        payload = await client.read_gatt_char(characteristic_uuid)
        return bytes(payload)

    async def write(self, device_id: str, characteristic_uuid: str, data: bytes) -> None:
        client = self._require_client(device_id)
        await client.write_gatt_char(characteristic_uuid, data)

    async def services(self, device_id: str) -> list[BleServiceInfo]:
        client = self._require_client(device_id)
        services = client.services
        if services is None:
            services = await client.get_services()
        return [
            BleServiceInfo(
                uuid=service.uuid,
                description=service.description,
                characteristics=tuple(
                    BleCharacteristicInfo(
                        uuid=characteristic.uuid,
                        properties=tuple(characteristic.properties),
                    )
                    for characteristic in service.characteristics
                ),
            )
            for service in services
        ]

    def set_disconnect_callback(
        self,
        device_id: str,
        callback: BleDisconnectCallback | None,
    ) -> None:
        if callback is None:
            self._disconnect_callbacks.pop(device_id, None)
        else:
            self._disconnect_callbacks[device_id] = callback

    def _require_client(self, device_id: str) -> BleakClient:
        client = self._clients.get(device_id)
        if client is None or not client.is_connected:
            raise RuntimeError(f"Device {device_id!r} is not connected.")
        return client
