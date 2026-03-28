from __future__ import annotations

from collections.abc import Callable

from fluke_app.bus import EventBus
from fluke_app.reading_stream import ReadingStreamService
from fluke_ble.adapter import BleAdapter, BleDevice
from fluke_core import ConnectionState, DeviceInfo, Reading
from fluke_protocol.profiles.base import DeviceProfile
from fluke_protocol.registry import ProfileRegistry


class DeviceManager:
    def __init__(
        self,
        ble_adapter: BleAdapter,
        profile_registry: ProfileRegistry,
        event_bus: EventBus | None = None,
        reading_stream: ReadingStreamService | None = None,
    ) -> None:
        self._ble = ble_adapter
        self._profiles = profile_registry
        self._bus = event_bus
        self._reading_stream = reading_stream or ReadingStreamService(event_bus)
        self._state = ConnectionState.IDLE
        self._active_device_id: str | None = None
        self._active_device: DeviceInfo | None = None
        self._active_profile: DeviceProfile | None = None
        self._scanned_devices: dict[str, DeviceInfo] = {}
        self._reading_handlers: list[Callable[[Reading], None]] = []
        self._subscribed_characteristics: set[str] = set()
        self._last_device_id: str | None = None
        self._last_profile_id: str | None = None

    async def scan(self, timeout_s: float = 5.0) -> list[DeviceInfo]:
        self._state = ConnectionState.SCANNING
        try:
            discovered = await self._ble.scan(timeout_s=timeout_s)
            devices = [self._to_device_info(device) for device in discovered]
            self._scanned_devices = {device.device_id: device for device in devices}
            self._state = ConnectionState.IDLE
            return devices
        except Exception:
            self._state = ConnectionState.ERROR
            raise

    async def connect(self, device_id: str, profile_id: str | None = None) -> DeviceInfo:
        self._state = ConnectionState.CONNECTING
        try:
            device = self._scanned_devices.get(device_id)
            profile = self._resolve_profile(device, profile_id)
            await self._ble.connect(device_id)

            if device is None:
                device = DeviceInfo(
                    device_id=device_id,
                    ble_address=device_id,
                    model_name=profile.model_name,
                    profile_id=profile.profile_id,
                    support_level="supported" if profile_id else "assumed",
                    capabilities=profile.capabilities(),
                )

            self._active_device_id = device_id
            self._active_device = device
            self._active_profile = profile
            self._last_device_id = device_id
            self._last_profile_id = profile.profile_id
            self._state = ConnectionState.CONNECTED
            return device
        except Exception:
            self._state = ConnectionState.ERROR
            raise

    async def start_stream(self) -> None:
        if self._active_device_id is None or self._active_profile is None:
            raise RuntimeError("Connect to a device before starting the stream.")

        if self._state == ConnectionState.STREAMING:
            return

        try:
            for characteristic_uuid in self._active_profile.notification_characteristics():
                if characteristic_uuid in self._subscribed_characteristics:
                    continue

                async def _on_payload(payload: bytes, *, _char_uuid: str = characteristic_uuid) -> None:
                    readings = self._active_profile.parse_notification(
                        characteristic_uuid=_char_uuid,
                        payload=payload,
                        device_id=self._active_device_id or "",
                    )
                    if not readings:
                        return
                    self._reading_stream.on_readings(readings)
                    for reading in readings:
                        for handler in list(self._reading_handlers):
                            handler(reading)

                await self._ble.subscribe(self._active_device_id, characteristic_uuid, _on_payload)
                self._subscribed_characteristics.add(characteristic_uuid)

            self._state = ConnectionState.STREAMING
        except Exception:
            self._state = ConnectionState.ERROR
            raise

    async def reconnect(self) -> DeviceInfo:
        if self._last_device_id is None:
            raise RuntimeError("No previous device is available for reconnect.")
        self._state = ConnectionState.RECONNECTING
        return await self.connect(self._last_device_id, profile_id=self._last_profile_id)

    async def disconnect(self) -> None:
        if self._active_device_id is None:
            self._state = ConnectionState.IDLE
            return

        for characteristic_uuid in list(self._subscribed_characteristics):
            try:
                await self._ble.unsubscribe(self._active_device_id, characteristic_uuid)
            except Exception:
                pass
        self._subscribed_characteristics.clear()

        if self._active_profile is not None:
            self._active_profile.reset_device(self._active_device_id)

        try:
            await self._ble.disconnect(self._active_device_id)
        finally:
            self._active_device_id = None
            self._active_device = None
            self._active_profile = None
            self._state = ConnectionState.DISCONNECTED

    def state(self) -> ConnectionState:
        return self._state

    def latest_reading(self) -> Reading | None:
        return self._reading_stream.latest()

    def active_device(self) -> DeviceInfo | None:
        return self._active_device

    def last_device_id(self) -> str | None:
        return self._last_device_id

    def subscribe_readings(self, handler: Callable[[Reading], None]) -> None:
        self._reading_handlers.append(handler)

    def _to_device_info(self, device: BleDevice) -> DeviceInfo:
        profile = self._profiles.resolve(device.name, device.metadata)
        return DeviceInfo(
            device_id=device.id,
            ble_address=device.address,
            model_name=profile.model_name if profile is not None else (device.name or "Unknown Device"),
            profile_id=profile.profile_id if profile is not None else "",
            nickname=device.name,
            support_level="supported" if profile is not None else "unknown",
            capabilities=profile.capabilities() if profile is not None else [],
            rssi=device.rssi,
            metadata=dict(device.metadata),
        )

    def _resolve_profile(self, device: DeviceInfo | None, profile_id: str | None) -> DeviceProfile:
        if profile_id:
            profile = self._profiles.get(profile_id)
            if profile is None:
                raise RuntimeError(f"Unknown profile {profile_id!r}.")
            return profile

        if device is not None:
            profile = self._profiles.get(device.profile_id)
            if profile is not None:
                return profile
            profile = self._profiles.resolve(device.nickname, device.metadata)
            if profile is not None:
                return profile

        default_profile = self._profiles.default()
        if default_profile is None:
            raise RuntimeError("Could not resolve a device profile. Scan first or provide --profile.")
        return default_profile
