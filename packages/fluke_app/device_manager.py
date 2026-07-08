from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from fluke_app.bus import EventBus
from fluke_app.reading_stream import ReadingStreamService
from fluke_app.reconnect_policy import ReconnectPolicy
from fluke_ble.adapter import BleAdapter, BleDevice
from fluke_core import ConnectionState, DeviceInfo, Reading
from fluke_protocol.profiles.base import DeviceFamilyRuntime, DeviceMatch, DeviceProfile, DeviceServiceSet
from fluke_protocol.registry import ProfileRegistry


@dataclass(frozen=True, slots=True)
class ConnectionRetryPolicy:
    scan_passes: int = 2
    default_scan_timeout_s: float = 2.5
    initial_connect_attempts: int = 3
    connect_timeout_s: float = 10.0
    connect_backoff_s: tuple[float, ...] = (0.5, 1.0)
    rescan_rounds: int = 2
    rescan_passes: int = 2
    rescan_timeout_s: float = 2.5
    rescan_connect_attempts: int = 2
    recovery_window_s: float = 20.0
    recovery_direct_attempts: int = 2
    recovery_scan_rounds: int = 2
    recovery_scan_passes: int = 2
    recovery_scan_timeout_s: float = 2.5
    recovery_scan_connect_attempts: int = 2
    recovery_backoff_s: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0)
    stream_start_attempts: int = 2
    stream_start_timeout_s: float = 6.0


@dataclass(frozen=True, slots=True)
class ConnectionAttemptStatus:
    phase: str
    target_device_id: str
    attempt: int
    total_attempts: int
    is_recovery: bool
    message: str
    last_error_text: str = ""
    is_terminal: bool = False
    window_elapsed_s: float = 0.0
    window_total_s: float = 0.0


@dataclass(frozen=True, slots=True)
class ConnectionStateChanged:
    """Richer connection-state event published on the shared ``EventBus``.

    Surfaces (desktop/CLI/SDK) subscribe to this to render CONNECTED /
    RECONNECTING (with attempt count) / DISCONNECTED without polling.
    """

    state: ConnectionState
    attempt: int = 0
    total_attempts: int = 0
    is_recovery: bool = False
    message: str = ""
    device_id: str | None = None


def _phase_to_state(phase: str, is_recovery: bool) -> ConnectionState | None:
    if phase == "recovery_waiting":
        return ConnectionState.RECONNECTING
    if phase in ("direct_connect", "rescan", "stream_start"):
        return ConnectionState.RECONNECTING if is_recovery else ConnectionState.CONNECTING
    if phase in ("connected", "recovered"):
        return ConnectionState.CONNECTED
    if phase in ("connect_failed", "recovery_failed"):
        return ConnectionState.ERROR
    return None


class DeviceManager:
    def __init__(
        self,
        ble_adapter: BleAdapter,
        profile_registry: ProfileRegistry,
        event_bus: EventBus | None = None,
        reading_stream: ReadingStreamService | None = None,
        retry_policy: ConnectionRetryPolicy | None = None,
        reconnect_policy: ReconnectPolicy | None = None,
        auto_reconnect: bool = True,
    ) -> None:
        self._ble = ble_adapter
        self._profiles = profile_registry
        self._bus = event_bus
        self._reading_stream = reading_stream or ReadingStreamService(event_bus)
        self._retry_policy = retry_policy or ConnectionRetryPolicy()
        self._reconnect_policy = reconnect_policy or ReconnectPolicy()
        self._auto_reconnect = bool(auto_reconnect)
        self._recovery_attempt = 0
        self._state = ConnectionState.IDLE
        self._active_device_id: str | None = None
        self._active_device: DeviceInfo | None = None
        self._active_match: DeviceMatch | None = None
        self._active_runtime: DeviceFamilyRuntime | None = None
        self._scanned_devices: dict[str, DeviceInfo] = {}
        self._reading_handlers: list[Callable[[Reading], None]] = []
        self._notification_handlers: list[Callable[[str, bytes], None]] = []
        self._disconnect_handlers: list[Callable[[], None]] = []
        self._diagnostic_handlers: list[Callable[[ConnectionAttemptStatus], None]] = []
        self._subscribed_characteristics: set[str] = set()
        self._last_device_id: str | None = None
        self._last_profile_id: str | None = None
        self._last_device_info: DeviceInfo | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._latest_connection_diagnostics: ConnectionAttemptStatus | None = None
        self._recovery_task: asyncio.Task[None] | None = None
        self._recovery_enabled = False
        self._explicit_disconnect = False

    async def scan(self, timeout_s: float = 5.0) -> list[DeviceInfo]:
        self._remember_running_loop()
        self._state = ConnectionState.SCANNING
        try:
            devices = await self._scan_aggregated(timeout_s=timeout_s, update_cache=True)
            self._state = ConnectionState.IDLE
            return devices
        except Exception:
            self._state = ConnectionState.ERROR
            raise

    async def connect(self, device_id: str, profile_id: str | None = None) -> DeviceInfo:
        self._remember_running_loop()
        self._cancel_recovery_task()
        self._recovery_enabled = False
        self._explicit_disconnect = False
        self._state = ConnectionState.CONNECTING
        try:
            return await self._connect_low_level(device_id, profile_id=profile_id, candidate_device=None)
        except Exception:
            self._state = ConnectionState.ERROR
            raise

    async def establish_session(self, device_id: str, profile_id: str | None = None) -> DeviceInfo:
        self._remember_running_loop()
        self._cancel_recovery_task()
        self._recovery_enabled = False
        self._explicit_disconnect = False
        device = await self._establish_with_retry(
            target_device_id=device_id,
            profile_id=profile_id,
            is_recovery=False,
        )
        self._recovery_enabled = self._reconnect_active()
        return device

    async def start_stream(self) -> None:
        self._remember_running_loop()
        if self._active_device_id is None or self._active_runtime is None:
            raise RuntimeError("Connect to a device before starting the stream.")

        if self._state == ConnectionState.STREAMING:
            return

        try:
            for characteristic_uuid in self._active_runtime.notification_subscriptions():
                if characteristic_uuid in self._subscribed_characteristics:
                    continue

                async def _on_payload(payload: bytes, *, _char_uuid: str = characteristic_uuid) -> None:
                    if self._active_runtime is None:
                        return
                    for handler in list(self._notification_handlers):
                        handler(_char_uuid, bytes(payload))
                    readings = self._active_runtime.parse_notification(
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
            self._publish_connection_state(ConnectionState.STREAMING, message="Streaming.")
        except Exception:
            self._state = ConnectionState.ERROR
            raise

    async def reconnect(self) -> DeviceInfo:
        if self._last_device_id is None:
            raise RuntimeError("No previous device is available for reconnect.")
        self._state = ConnectionState.RECONNECTING
        return await self.connect(self._last_device_id, profile_id=self._last_profile_id)

    async def restore_session(self) -> DeviceInfo:
        self._remember_running_loop()
        if self._last_device_id is None:
            raise RuntimeError("No previous device is available for reconnect.")
        self._state = ConnectionState.RECONNECTING
        device = await self._establish_with_retry(
            target_device_id=self._last_device_id,
            profile_id=self._last_profile_id,
            is_recovery=True,
        )
        self._recovery_enabled = self._reconnect_active()
        return device

    async def disconnect(self) -> None:
        self._remember_running_loop()
        self._explicit_disconnect = True
        self._recovery_enabled = False
        self._cancel_recovery_task()
        await self._disconnect_active(set_idle_if_empty=True)
        self._latest_connection_diagnostics = None
        self._publish_connection_state(self._state, message="Disconnected.")

    def state(self) -> ConnectionState:
        return self._state

    def reconnect_policy(self) -> ReconnectPolicy:
        return self._reconnect_policy

    def auto_reconnect_enabled(self) -> bool:
        return self._auto_reconnect and self._reconnect_policy.enabled

    def set_auto_reconnect(self, enabled: bool) -> None:
        """Enable/disable automatic reconnect at runtime (used by the desktop setting).

        Disabling while a recovery episode is in flight cancels it.
        """
        self._auto_reconnect = bool(enabled)
        if not self._auto_reconnect:
            self._recovery_enabled = False
            self._cancel_recovery_task()

    def _reconnect_active(self) -> bool:
        return self._auto_reconnect and self._reconnect_policy.enabled

    def latest_reading(self) -> Reading | None:
        return self._reading_stream.latest()

    def active_device(self) -> DeviceInfo | None:
        return self._active_device

    def active_capabilities(self) -> tuple[str, ...]:
        if self._active_runtime is None:
            return ()
        return self._active_runtime.capabilities()

    def active_family_id(self) -> str | None:
        if self._active_runtime is None:
            return None
        return self._active_runtime.family_id()

    def active_variant_id(self) -> str | None:
        if self._active_runtime is None:
            return None
        return self._active_runtime.variant_id()

    def active_runtime_services(self) -> DeviceServiceSet:
        if self._active_runtime is None:
            return DeviceServiceSet()
        return self._active_runtime.services()

    def ble_adapter(self) -> BleAdapter:
        return self._ble

    def last_device_id(self) -> str | None:
        return self._last_device_id

    def latest_connection_diagnostics(self) -> ConnectionAttemptStatus | None:
        return self._latest_connection_diagnostics

    def subscribe_readings(self, handler: Callable[[Reading], None]) -> None:
        self._reading_handlers.append(handler)

    def subscribe_notifications(self, handler: Callable[[str, bytes], None]) -> None:
        self._notification_handlers.append(handler)

    def subscribe_disconnects(self, handler: Callable[[], None]) -> None:
        self._disconnect_handlers.append(handler)

    def subscribe_connection_diagnostics(self, handler: Callable[[ConnectionAttemptStatus], None]) -> None:
        self._diagnostic_handlers.append(handler)

    def _remember_running_loop(self) -> None:
        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            return

    async def _scan_aggregated(
        self,
        *,
        timeout_s: float,
        update_cache: bool,
        passes: int | None = None,
    ) -> list[DeviceInfo]:
        passes = max(1, int(passes or self._retry_policy.scan_passes))
        total_timeout = float(timeout_s if timeout_s > 0 else self._retry_policy.default_scan_timeout_s * passes)
        per_pass_timeout = max(0.05, total_timeout / passes)

        merged: dict[str, BleDevice] = {}
        counts: dict[str, int] = {}
        for _ in range(passes):
            discovered = await self._ble.scan(timeout_s=per_pass_timeout)
            for device in discovered:
                key = self._scan_merge_key(device)
                counts[key] = counts.get(key, 0) + 1
                existing = merged.get(key)
                merged[key] = device if existing is None else self._merge_ble_devices(existing, device)

        observed_at = datetime.now(timezone.utc).isoformat()
        devices: list[DeviceInfo] = []
        cache: dict[str, DeviceInfo] = {}
        for key, device in merged.items():
            metadata = dict(device.metadata)
            metadata["scan_seen_count"] = counts.get(key, 1)
            metadata["last_seen_at"] = observed_at
            device_info = self._to_device_info(replace(device, metadata=metadata))
            devices.append(device_info)
            cache[device_info.device_id] = device_info

        devices.sort(key=lambda item: ((item.rssi or -9999) * -1, item.model_name.lower(), item.device_id))
        if update_cache:
            self._scanned_devices = cache
        return devices

    async def _connect_low_level(
        self,
        device_id: str,
        *,
        profile_id: str | None,
        candidate_device: DeviceInfo | None,
    ) -> DeviceInfo:
        device = candidate_device or self._scanned_devices.get(device_id)
        profile, match = self._resolve_profile_and_match(device, profile_id)
        runtime = profile.create_runtime(match)
        ble_address = None if device is None else device.ble_address
        await self._ble.connect(
            device_id,
            ble_address=ble_address,
            timeout_s=self._retry_policy.connect_timeout_s,
        )
        self._ble.set_disconnect_callback(device_id, self._on_unexpected_disconnect)
        runtime.initialize(match.to_connection_context(device_id=device_id))

        if device is None:
            device = DeviceInfo(
                device_id=device_id,
                ble_address=device_id,
                model_name=match.model_hint,
                profile_id=profile.profile_id,
                family_id=match.family_id,
                variant_id=match.variant_id,
                support_level="supported" if profile_id else "assumed",
                capabilities=list(match.capabilities),
            )
        else:
            device = replace(
                device,
                profile_id=profile.profile_id,
                family_id=match.family_id,
                variant_id=match.variant_id,
                model_name=match.model_hint or device.model_name,
                support_level="supported" if profile_id or device.support_level == "supported" else device.support_level,
                capabilities=list(match.capabilities or tuple(device.capabilities)),
            )

        self._active_device_id = device_id
        self._active_device = device
        self._active_match = match
        self._active_runtime = runtime
        self._last_device_id = device_id
        self._last_profile_id = profile.profile_id
        self._last_device_info = device
        self._state = ConnectionState.CONNECTED
        return device

    async def _establish_with_retry(
        self,
        *,
        target_device_id: str,
        profile_id: str | None,
        is_recovery: bool,
    ) -> DeviceInfo:
        start = asyncio.get_running_loop().time()
        policy = self._retry_policy
        last_error: Exception | None = None
        last_direct_error: Exception | None = None
        target_device = self._last_device_info if self._last_device_id == target_device_id else self._scanned_devices.get(target_device_id)
        if is_recovery:
            self._recovery_attempt = 0

        direct_attempts = policy.recovery_direct_attempts if is_recovery else policy.initial_connect_attempts
        total_direct = max(1, direct_attempts)
        for attempt in range(1, total_direct + 1):
            if is_recovery and self._recovery_window_exhausted(start):
                break
            if is_recovery:
                self._recovery_attempt += 1
            self._emit_diagnostics(
                phase="direct_connect",
                target_device_id=target_device_id,
                attempt=attempt,
                total_attempts=total_direct,
                is_recovery=is_recovery,
                message=f"Attempting BLE connect ({attempt}/{total_direct}).",
                last_error_text="" if last_error is None else str(last_error),
                started_at=start,
            )
            try:
                device = await self._establish_once(
                    device_id=target_device_id,
                    profile_id=profile_id,
                    candidate_device=target_device,
                    is_recovery=is_recovery,
                    started_at=start,
                )
                self._emit_diagnostics(
                    phase="recovered" if is_recovery else "connected",
                    target_device_id=device.device_id,
                    attempt=attempt,
                    total_attempts=total_direct,
                    is_recovery=is_recovery,
                    message="Connection restored." if is_recovery else "Connected and streaming.",
                    started_at=start,
                    is_terminal=True,
                )
                return device
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                last_direct_error = exc
                await self._disconnect_active(set_idle_if_empty=False)
                delay = self._retry_backoff(attempt - 1, is_recovery=is_recovery)
                if attempt < total_direct and delay > 0 and not (is_recovery and self._recovery_window_exhausted(start, extra_s=delay)):
                    await asyncio.sleep(delay)

        scan_rounds = policy.recovery_scan_rounds if is_recovery else policy.rescan_rounds
        scan_passes = policy.recovery_scan_passes if is_recovery else policy.rescan_passes
        scan_timeout = policy.recovery_scan_timeout_s if is_recovery else policy.rescan_timeout_s
        scan_connect_attempts = policy.recovery_scan_connect_attempts if is_recovery else policy.rescan_connect_attempts

        for round_index in range(1, max(1, scan_rounds) + 1):
            if is_recovery and self._recovery_window_exhausted(start):
                break
            self._emit_diagnostics(
                phase="rescan",
                target_device_id=target_device_id,
                attempt=round_index,
                total_attempts=max(1, scan_rounds),
                is_recovery=is_recovery,
                message=f"Scanning for meter visibility ({round_index}/{max(1, scan_rounds)}).",
                last_error_text="" if last_error is None else str(last_error),
                started_at=start,
            )
            scanned_devices = await self._scan_aggregated(
                timeout_s=max(0.1, scan_timeout * max(1, scan_passes)),
                update_cache=False,
                passes=scan_passes,
            )
            candidate = self._select_recovery_candidate(
                target_device_id=target_device_id,
                target_device=target_device,
                scanned_devices=scanned_devices,
            )
            if candidate is None:
                detail = "Meter not advertising in the recovery scan window."
                if target_device is not None:
                    detail = "Meter was visible in the earlier scan but is not advertising in the recovery scan window."
                if last_direct_error is not None:
                    detail = f"{detail} Last direct-connect error: {_exception_text(last_direct_error)}"
                last_error = RuntimeError(detail)
                continue
            target_device = candidate
            for attempt in range(1, max(1, scan_connect_attempts) + 1):
                if is_recovery and self._recovery_window_exhausted(start):
                    break
                if is_recovery:
                    self._recovery_attempt += 1
                self._emit_diagnostics(
                    phase="direct_connect",
                    target_device_id=candidate.device_id,
                    attempt=attempt,
                    total_attempts=max(1, scan_connect_attempts),
                    is_recovery=is_recovery,
                    message=f"Trying scanned candidate {candidate.device_id} ({attempt}/{max(1, scan_connect_attempts)}).",
                    last_error_text="" if last_error is None else str(last_error),
                    started_at=start,
                )
                try:
                    device = await self._establish_once(
                        device_id=candidate.device_id,
                        profile_id=profile_id or candidate.profile_id or None,
                        candidate_device=candidate,
                        is_recovery=is_recovery,
                        started_at=start,
                    )
                    self._emit_diagnostics(
                        phase="recovered" if is_recovery else "connected",
                        target_device_id=device.device_id,
                        attempt=attempt,
                        total_attempts=max(1, scan_connect_attempts),
                        is_recovery=is_recovery,
                        message="Connection restored." if is_recovery else "Connected and streaming.",
                        started_at=start,
                        is_terminal=True,
                    )
                    return device
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = exc
                    last_direct_error = exc
                    await self._disconnect_active(set_idle_if_empty=False)
                    delay = self._retry_backoff(attempt - 1, is_recovery=is_recovery)
                    if attempt < max(1, scan_connect_attempts) and delay > 0 and not (
                        is_recovery and self._recovery_window_exhausted(start, extra_s=delay)
                    ):
                        await asyncio.sleep(delay)

        detail = "Connection failed."
        if is_recovery:
            detail = "Automatic reconnect failed within the recovery window."
        if last_error is not None:
            last_error_text = _exception_text(last_error)
            if "Last direct-connect error:" in last_error_text:
                detail = f"{detail} {last_error_text}"
            else:
                detail = f"{detail} Last error: {last_error_text}"
        self._emit_diagnostics(
            phase="recovery_failed" if is_recovery else "connect_failed",
            target_device_id=target_device_id,
            attempt=0,
            total_attempts=0,
            is_recovery=is_recovery,
            message=detail,
            last_error_text="" if last_error is None else str(last_error),
            started_at=start,
            is_terminal=True,
        )
        self._state = ConnectionState.ERROR
        raise RuntimeError(detail)

    async def _establish_once(
        self,
        *,
        device_id: str,
        profile_id: str | None,
        candidate_device: DeviceInfo | None,
        is_recovery: bool,
        started_at: float,
    ) -> DeviceInfo:
        device = await self._connect_low_level(
            device_id,
            profile_id=profile_id,
            candidate_device=candidate_device,
        )
        stream_error: Exception | None = None
        for stream_attempt in range(1, max(1, self._retry_policy.stream_start_attempts) + 1):
            self._emit_diagnostics(
                phase="stream_start",
                target_device_id=device.device_id,
                attempt=stream_attempt,
                total_attempts=max(1, self._retry_policy.stream_start_attempts),
                is_recovery=is_recovery,
                message=f"Starting notification stream ({stream_attempt}/{max(1, self._retry_policy.stream_start_attempts)}).",
                last_error_text="" if stream_error is None else str(stream_error),
                started_at=started_at,
            )
            try:
                await asyncio.wait_for(self.start_stream(), timeout=self._retry_policy.stream_start_timeout_s)
                return self._active_device or device
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stream_error = exc
                await self._disconnect_active(set_idle_if_empty=False)
                if stream_attempt >= max(1, self._retry_policy.stream_start_attempts):
                    break
                device = await self._connect_low_level(
                    device_id,
                    profile_id=profile_id,
                    candidate_device=candidate_device,
                )
        raise RuntimeError(f"Failed to start BLE notifications: {stream_error}")

    async def _disconnect_active(self, *, set_idle_if_empty: bool) -> None:
        if self._active_device_id is None:
            self._state = ConnectionState.IDLE if set_idle_if_empty else ConnectionState.DISCONNECTED
            return

        device_id = self._active_device_id
        self._ble.set_disconnect_callback(device_id, None)

        for characteristic_uuid in list(self._subscribed_characteristics):
            try:
                await self._ble.unsubscribe(device_id, characteristic_uuid)
            except Exception:
                pass
        self._subscribed_characteristics.clear()

        if self._active_runtime is not None:
            self._active_runtime.reset_device(device_id)

        try:
            await self._ble.disconnect(device_id)
        finally:
            self._active_device_id = None
            self._active_device = None
            self._active_match = None
            self._active_runtime = None
            self._state = ConnectionState.IDLE if set_idle_if_empty else ConnectionState.DISCONNECTED

    def _on_unexpected_disconnect(self, device_id: str) -> None:
        if device_id != self._active_device_id:
            return

        last_device = self._active_device or self._last_device_info
        if self._active_runtime is not None:
            self._active_runtime.reset_device(device_id)
        self._subscribed_characteristics.clear()
        self._active_device_id = None
        self._active_device = None
        self._active_match = None
        self._active_runtime = None
        self._last_device_info = last_device
        self._state = ConnectionState.DISCONNECTED
        self._publish_connection_state(
            ConnectionState.DISCONNECTED,
            is_recovery=False,
            message="Connection lost.",
            device_id=device_id,
        )

        if self._explicit_disconnect:
            return
        if not self._recovery_enabled or not self._reconnect_active():
            self._notify_terminal_disconnects()
            return
        loop = self._event_loop
        if loop is None:
            self._notify_terminal_disconnects()
            return
        loop.call_soon_threadsafe(self._schedule_recovery)

    def _schedule_recovery(self) -> None:
        if self._recovery_task is not None and not self._recovery_task.done():
            return
        self._state = ConnectionState.RECONNECTING
        target = self._last_device_id or (self._last_device_info.device_id if self._last_device_info is not None else "")
        self._emit_diagnostics(
            phase="recovery_waiting",
            target_device_id=target,
            attempt=0,
            total_attempts=0,
            is_recovery=True,
            message="Connection lost. Automatic recovery started.",
        )
        self._recovery_task = asyncio.create_task(self._run_recovery_task())

    async def _run_recovery_task(self) -> None:
        try:
            await self.restore_session()
        except asyncio.CancelledError:
            return
        except Exception:
            self._recovery_enabled = False
            self._notify_terminal_disconnects()
        finally:
            if self._recovery_task is asyncio.current_task():
                self._recovery_task = None

    def _cancel_recovery_task(self) -> None:
        task = self._recovery_task
        self._recovery_task = None
        if task is not None and not task.done():
            task.cancel()

    def _notify_terminal_disconnects(self) -> None:
        self._state = ConnectionState.ERROR if self._latest_connection_diagnostics and self._latest_connection_diagnostics.is_recovery else ConnectionState.DISCONNECTED
        self._publish_connection_state(
            self._state,
            is_recovery=bool(self._latest_connection_diagnostics and self._latest_connection_diagnostics.is_recovery),
            message="Automatic reconnect gave up." if self._state == ConnectionState.ERROR else "Disconnected.",
        )
        for handler in list(self._disconnect_handlers):
            try:
                handler()
            except Exception:
                pass

    def _publish_connection_state(
        self,
        state: ConnectionState,
        *,
        attempt: int = 0,
        total_attempts: int = 0,
        is_recovery: bool = False,
        message: str = "",
        device_id: str | None = None,
    ) -> None:
        if self._bus is None:
            return
        self._bus.publish(
            ConnectionStateChanged(
                state=state,
                attempt=attempt,
                total_attempts=total_attempts,
                is_recovery=is_recovery,
                message=message,
                device_id=device_id if device_id is not None else self._active_device_id,
            )
        )

    def _emit_diagnostics(
        self,
        *,
        phase: str,
        target_device_id: str,
        attempt: int,
        total_attempts: int,
        is_recovery: bool,
        message: str,
        last_error_text: str = "",
        started_at: float | None = None,
        is_terminal: bool = False,
    ) -> None:
        elapsed = 0.0
        window_total = self._effective_give_up_s() if is_recovery else 0.0
        if started_at is not None:
            elapsed = max(0.0, asyncio.get_running_loop().time() - started_at)
        status = ConnectionAttemptStatus(
            phase=phase,
            target_device_id=target_device_id,
            attempt=attempt,
            total_attempts=total_attempts,
            is_recovery=is_recovery,
            message=message,
            last_error_text=last_error_text,
            is_terminal=is_terminal,
            window_elapsed_s=elapsed,
            window_total_s=window_total,
        )
        self._latest_connection_diagnostics = status
        mapped_state = _phase_to_state(phase, is_recovery)
        if mapped_state is not None:
            self._publish_connection_state(
                mapped_state,
                attempt=attempt,
                total_attempts=total_attempts,
                is_recovery=is_recovery,
                message=message,
                device_id=target_device_id,
            )
        for handler in list(self._diagnostic_handlers):
            try:
                handler(status)
            except Exception:
                pass

    def _retry_backoff(self, index: int, *, is_recovery: bool) -> float:
        if is_recovery:
            # Recovery backoff is driven by the dedicated ReconnectPolicy so the
            # delay grows exponentially (with jitter) across the whole episode.
            return self._reconnect_policy.delay_for(max(1, self._recovery_attempt))
        values = self._retry_policy.connect_backoff_s
        if not values:
            return 0.0
        bounded_index = max(0, min(index, len(values) - 1))
        return max(0.0, float(values[bounded_index]))

    def _effective_give_up_s(self) -> float:
        give_up = self._reconnect_policy.give_up_after_s
        if give_up and give_up > 0:
            return float(give_up)
        return float(self._retry_policy.recovery_window_s)

    def _recovery_attempts_exhausted(self) -> bool:
        max_attempts = self._reconnect_policy.max_attempts
        if max_attempts <= 0:
            return False
        return self._recovery_attempt >= max_attempts

    def _recovery_window_exhausted(self, started_at: float, *, extra_s: float = 0.0) -> bool:
        if self._recovery_attempts_exhausted():
            return True
        give_up = self._effective_give_up_s()
        if give_up <= 0:
            return False
        elapsed = asyncio.get_running_loop().time() - started_at + max(0.0, extra_s)
        return elapsed >= give_up

    def _select_recovery_candidate(
        self,
        *,
        target_device_id: str,
        target_device: DeviceInfo | None,
        scanned_devices: list[DeviceInfo],
    ) -> DeviceInfo | None:
        if not scanned_devices:
            return None
        by_id = {device.device_id: device for device in scanned_devices}
        exact = by_id.get(target_device_id)
        if exact is not None:
            return exact
        if target_device is not None and target_device.ble_address:
            for device in scanned_devices:
                if device.ble_address and device.ble_address.lower() == target_device.ble_address.lower():
                    return device
        target_names = {
            str(target_device.nickname or "").strip().lower(),
            str(target_device.model_name or "").strip().lower(),
        } if target_device is not None else set()
        target_profile = "" if target_device is None else str(target_device.profile_id or "").strip().lower()
        for device in scanned_devices:
            if target_profile and str(device.profile_id or "").strip().lower() == target_profile:
                candidate_names = {
                    str(device.nickname or "").strip().lower(),
                    str(device.model_name or "").strip().lower(),
                }
                if candidate_names & target_names:
                    return device
        return None

    def _scan_merge_key(self, device: BleDevice) -> str:
        address = (device.address or "").strip().lower()
        if address:
            return f"addr:{address}"
        return f"id:{(device.id or '').strip().lower()}"

    def _merge_ble_devices(self, existing: BleDevice, current: BleDevice) -> BleDevice:
        metadata = dict(existing.metadata)
        for key, value in current.metadata.items():
            if key == "service_uuids":
                merged = {str(item).lower() for item in metadata.get(key, []) if isinstance(item, str)}
                merged.update(str(item).lower() for item in value if isinstance(item, str))
                metadata[key] = sorted(merged)
            elif key == "manufacturer_data_ids":
                merged_ids = {int(item) for item in metadata.get(key, []) if isinstance(item, int)}
                merged_ids.update(int(item) for item in value if isinstance(item, int))
                metadata[key] = sorted(merged_ids)
            elif key not in metadata or metadata[key] in (None, "", [], {}):
                metadata[key] = value
        rssi_values = [item for item in (existing.rssi, current.rssi) if item is not None]
        return BleDevice(
            id=current.id or existing.id,
            name=current.name or existing.name,
            address=current.address or existing.address,
            rssi=max(rssi_values) if rssi_values else None,
            metadata=metadata,
        )

    def _to_device_info(self, device: BleDevice) -> DeviceInfo:
        match = self._profiles.resolve(device.name, device.metadata)
        return DeviceInfo(
            device_id=device.id,
            ble_address=device.address,
            model_name=match.model_hint if match is not None else (device.name or "Unknown Device"),
            profile_id=match.profile_id if match is not None else "",
            family_id=match.family_id if match is not None else "",
            variant_id=match.variant_id if match is not None else "",
            nickname=device.name,
            support_level="supported" if match is not None else "unknown",
            capabilities=list(match.capabilities) if match is not None else [],
            rssi=device.rssi,
            metadata=dict(device.metadata),
        )

    def _resolve_profile_and_match(self, device: DeviceInfo | None, profile_id: str | None) -> tuple[DeviceProfile, DeviceMatch]:
        if profile_id:
            profile = self._profiles.get(profile_id)
            if profile is None:
                raise RuntimeError(f"Unknown profile {profile_id!r}.")
            advertisement_name = None if device is None else (device.nickname or device.model_name)
            metadata = {} if device is None else dict(device.metadata)
            match = profile.create_match(advertisement_name, metadata) or self._forced_match(profile, advertisement_name, metadata)
            return profile, match

        if device is not None:
            profile = self._profiles.get(device.profile_id)
            if profile is not None:
                match = profile.create_match(device.nickname or device.model_name, dict(device.metadata)) or self._match_from_device(
                    profile,
                    device,
                )
                return profile, match
            match = self._profiles.resolve(device.nickname or device.model_name, device.metadata)
            if match is not None:
                profile = self._profiles.get(match.profile_id)
                if profile is not None:
                    return profile, match

        default_profile = self._profiles.default()
        if default_profile is None:
            raise RuntimeError("Could not resolve a device profile. Scan first or provide --profile.")
        advertisement_name = None if device is None else (device.nickname or device.model_name)
        metadata = {} if device is None else dict(device.metadata)
        match = default_profile.create_match(advertisement_name, metadata) or self._forced_match(
            default_profile,
            advertisement_name,
            metadata,
        )
        return default_profile, match

    def _forced_match(
        self,
        profile: DeviceProfile,
        advertisement_name: str | None,
        metadata: dict[str, object],
    ) -> DeviceMatch:
        return DeviceMatch(
            profile_id=profile.profile_id,
            family_id=profile.family_id(),
            variant_id=profile.variant_id(),
            score=1.0,
            display_name=profile.display_name(),
            model_hint=profile.model_name,
            capabilities=tuple(profile.capabilities()),
            advertisement_name=advertisement_name,
            metadata=dict(metadata),
        )

    def _match_from_device(self, profile: DeviceProfile, device: DeviceInfo) -> DeviceMatch:
        return DeviceMatch(
            profile_id=profile.profile_id,
            family_id=device.family_id or profile.family_id(),
            variant_id=device.variant_id or profile.variant_id(),
            score=1.0,
            display_name=device.model_name or profile.display_name(),
            model_hint=device.model_name or profile.model_name,
            capabilities=tuple(device.capabilities or profile.capabilities()),
            advertisement_name=device.nickname or device.model_name,
            metadata=dict(device.metadata),
        )


def _exception_text(exc: BaseException) -> str:
    text = str(exc).strip()
    if text:
        return text
    if isinstance(exc, TimeoutError):
        return "operation timed out"
    return exc.__class__.__name__
