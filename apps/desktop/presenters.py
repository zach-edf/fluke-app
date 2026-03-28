from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import threading

from apps.desktop.viewmodels import (
    DiscoveryViewModel,
    HomeViewModel,
    LiveReadingViewModel,
    RecentDeviceViewModel,
    ScannedDeviceViewModel,
    SettingsViewModel,
    SessionSummaryViewModel,
    SessionViewModel,
)
from fluke_app import ExportService, SessionRecorder, new_session
from fluke_app.export_service import SessionCsvExporter, SessionJsonExporter
from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_core.models.session import Session


class AppPresenter:
    def __init__(
        self,
        device_manager: object,
        store: object,
        app_version: str = "0.1.0",
        export_directory: str | Path = "exports",
    ) -> None:
        self._device_manager = device_manager
        self._store = store
        self._app_version = app_version
        self._export_directory = Path(export_directory)
        self._recorder = SessionRecorder(store.sessions, store.readings)
        self._export_service = ExportService(
            store.sessions,
            store.readings,
            SessionCsvExporter(),
            SessionJsonExporter(device_repo=store.devices),
        )
        self._lock = threading.Lock()
        self._home = HomeViewModel()
        self._discovery = DiscoveryViewModel()
        self._live = LiveReadingViewModel()
        self._session = SessionViewModel(database_path_text=str(store.path))
        self._settings = SettingsViewModel(
            database_path_text=str(store.path),
            export_directory_text=str(self._export_directory),
            diagnostics_text="PySide6 and BLE runtime configured.",
        )
        self._current_device: DeviceInfo | None = None
        self._last_completed_session_id: str | None = None
        self._device_manager.subscribe_readings(self._recorder.on_reading)
        self._device_manager.subscribe_readings(self.on_reading)
        self.refresh_recent_devices()
        self.refresh_recent_sessions()

    def home_view_model(self) -> HomeViewModel:
        with self._lock:
            return replace(self._home)

    def discovery_view_model(self) -> DiscoveryViewModel:
        with self._lock:
            return replace(self._discovery)

    def live_view_model(self) -> LiveReadingViewModel:
        with self._lock:
            return replace(self._live)

    def session_view_model(self) -> SessionViewModel:
        with self._lock:
            return replace(self._session)

    def settings_view_model(self) -> SettingsViewModel:
        with self._lock:
            return replace(self._settings)

    async def scan_devices(self, timeout_s: float = 5.0) -> tuple[ScannedDeviceViewModel, ...]:
        self._set_discovery(status_text="Scanning...")
        devices = await self._device_manager.scan(timeout_s=timeout_s)
        scanned = tuple(_device_vm(device) for device in devices)
        self._set_discovery(
            status_text=f"Found {len(scanned)} device(s)" if scanned else "No devices found",
            devices=scanned,
            selected_device_id=scanned[0].device_id if scanned else None,
        )
        self._report_message(f"Scan complete: {len(scanned)} device(s).")
        return scanned

    async def connect_device(self, device_id: str | None = None, profile_id: str | None = None) -> DeviceInfo:
        target_device_id = device_id or self._discovery.selected_device_id
        if not target_device_id:
            raise RuntimeError("Select a device before connecting.")

        self._set_connection_status("Connecting...")
        device = await self._device_manager.connect(target_device_id, profile_id=profile_id)
        self._store.upsert_device(device)
        await self._device_manager.start_stream()

        with self._lock:
            self._current_device = device
            label = device.nickname or device.model_name or device.device_id
            self._home = replace(
                self._home,
                connection_text=f"Connected to {label}",
                active_device_text=f"{label} ({device.device_id})",
            )
            self._live = replace(
                self._live,
                connection_text=f"Connected to {label}",
                status_text="Streaming",
            )
            self._discovery = replace(
                self._discovery,
                selected_device_id=device.device_id,
                status_text=f"Connected to {label}",
            )
            self._settings = replace(
                self._settings,
                diagnostics_text=f"Connected to {label}; BLE stream active.",
            )
        self.refresh_recent_devices()
        self.refresh_recent_sessions()
        return device

    async def reconnect_last_device(self) -> DeviceInfo:
        recent = self._store.devices.list_recent(limit=1)
        if not recent:
            raise RuntimeError("No recent device is stored yet.")
        last = recent[0]
        self.select_device(last.device_id)
        return await self.connect_device(device_id=last.device_id, profile_id=last.profile_id or None)

    async def disconnect_device(self) -> None:
        if self._recorder.active_session() is not None:
            self.stop_logging()
        await self._device_manager.disconnect()
        with self._lock:
            self._current_device = None
            self._home = replace(
                self._home,
                connection_text="Disconnected",
                active_device_text="No device connected",
            )
            self._live = replace(
                self._live,
                connection_text="Disconnected",
                status_text="Disconnected",
                is_logging=False,
                session_title=None,
            )
            self._discovery = replace(self._discovery, status_text="Disconnected")
            self._settings = replace(self._settings, diagnostics_text="Disconnected.")

    def start_logging(self, title: str | None = None, notes: str | None = None, tags: list[str] | None = None) -> str:
        if self._current_device is None:
            raise RuntimeError("Connect to a device before starting logging.")
        active = self._recorder.active_session()
        if active is not None:
            return active.session_id

        session = self._recorder.start(
            new_session(
                device_id=self._current_device.device_id,
                title=title,
                notes=notes,
                tags=tags or [],
                app_version=self._app_version,
                profile_id=self._current_device.profile_id,
            )
        )
        with self._lock:
            session_label = session.title or session.session_id
            self._home = replace(self._home, active_session_text=session_label)
            self._live = replace(
                self._live,
                is_logging=True,
                session_title=session_label,
            )
            self._session = replace(
                self._session,
                active_session_id=session.session_id,
                active_title_text=session_label,
                reading_count_text="0 readings",
                export_status_text="",
            )
        return session.session_id

    def stop_logging(self) -> Session | None:
        session = self._recorder.stop()
        if session is None:
            return None
        with self._lock:
            self._last_completed_session_id = session.session_id
            session_label = session.title or session.session_id
            self._live = replace(
                self._live,
                is_logging=False,
                session_title=session_label,
            )
            self._session = replace(
                self._session,
                active_session_id=session.session_id,
                active_title_text=session_label,
            )
            self._home = replace(self._home, active_session_text=session_label)
        self.refresh_recent_sessions()
        return session

    def export_session_csv(self, path: str | Path, session_id: str | None = None) -> str:
        target = self._resolve_export_session_id(session_id)
        export_path = self._resolve_export_path(path, "desktop_session.csv")
        exported = self._export_service.export_csv(target, export_path)
        with self._lock:
            self._session = replace(self._session, export_status_text=f"CSV exported to {exported}")
        return exported

    def export_session_json(self, path: str | Path, session_id: str | None = None) -> str:
        target = self._resolve_export_session_id(session_id)
        export_path = self._resolve_export_path(path, "desktop_session.json")
        exported = self._export_service.export_json(target, export_path)
        with self._lock:
            self._session = replace(self._session, export_status_text=f"JSON exported to {exported}")
        return exported

    def set_export_directory(self, path: str | Path) -> None:
        export_dir = Path(path)
        with self._lock:
            self._export_directory = export_dir
            self._settings = replace(self._settings, export_directory_text=str(export_dir))

    async def shutdown(self) -> None:
        if self._recorder.active_session() is not None:
            self.stop_logging()
        await self._device_manager.disconnect()

    def refresh_recent_devices(self, limit: int = 8) -> None:
        devices = self._store.devices.list_recent(limit=limit)
        rows = tuple(_recent_device_vm(device) for device in devices)
        with self._lock:
            self._home = replace(self._home, recent_devices=rows)

    def refresh_recent_sessions(self, limit: int = 10) -> None:
        sessions = self._store.sessions.list_recent(limit=limit)
        rows = tuple(_session_vm(session) for session in sessions)
        with self._lock:
            self._session = replace(self._session, recent_sessions=rows)

    def report_error(self, message: str) -> None:
        with self._lock:
            self._home = replace(self._home, message_text=message, connection_text=f"Error: {message}")
            self._discovery = replace(self._discovery, status_text=f"Error: {message}")
            self._session = replace(self._session, export_status_text=message)
            self._live = replace(self._live, status_text="Error")
            self._settings = replace(self._settings, diagnostics_text=message)

    def select_device(self, device_id: str | None) -> None:
        with self._lock:
            self._discovery = replace(self._discovery, selected_device_id=device_id)

    def on_reading(self, reading: Reading) -> None:
        value = "--" if reading.value is None else f"{reading.value:.6g}"
        timestamp = reading.timestamp_utc.astimezone(timezone.utc).strftime("%H:%M:%S UTC")
        with self._lock:
            active_session = self._recorder.active_session()
            is_logging = active_session is not None
            session_title = None if active_session is None else (active_session.title or active_session.session_id)
            self._live = replace(
                self._live,
                main_value=value,
                unit_text=reading.unit,
                measurement_label=reading.measurement_type.value.replace("_", " ").title(),
                status_text=reading.status.value.replace("_", " ").title(),
                session_title=session_title,
                is_logging=is_logging,
                last_updated_text=timestamp,
            )
            self._session = replace(
                self._session,
                reading_count_text=f"{self._recorder.reading_count()} readings",
            )

    def _resolve_export_session_id(self, session_id: str | None) -> str:
        target = session_id or self._last_completed_session_id
        if not target:
            active = self._recorder.active_session()
            target = None if active is None else active.session_id
        if not target:
            raise RuntimeError("No session available to export.")
        return target

    def _resolve_export_path(self, path: str | Path, default_name: str) -> Path:
        candidate = Path(path)
        if candidate.name != "." and str(candidate) not in {"", "."}:
            return candidate
        return self._export_directory / default_name

    def _set_connection_status(self, status: str) -> None:
        with self._lock:
            self._home = replace(self._home, connection_text=status)
            self._live = replace(self._live, connection_text=status)

    def _set_discovery(
        self,
        *,
        status_text: str,
        devices: tuple[ScannedDeviceViewModel, ...] | None = None,
        selected_device_id: str | None = None,
    ) -> None:
        with self._lock:
            self._discovery = replace(
                self._discovery,
                status_text=status_text,
                devices=self._discovery.devices if devices is None else devices,
                selected_device_id=self._discovery.selected_device_id
                if selected_device_id is None
                else selected_device_id,
            )

    def _report_message(self, message: str) -> None:
        with self._lock:
            self._home = replace(self._home, message_text=message)


def _device_vm(device: DeviceInfo) -> ScannedDeviceViewModel:
    label = device.nickname or device.model_name or device.device_id
    rssi_text = "-" if device.rssi is None else f"{device.rssi} dBm"
    support_text = device.support_level or "unknown"
    return ScannedDeviceViewModel(
        device_id=device.device_id,
        label=label,
        model_name=device.model_name,
        rssi_text=rssi_text,
        support_text=support_text,
    )


def _session_vm(session: Session) -> SessionSummaryViewModel:
    started = session.started_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ended = "-" if session.ended_at is None else session.ended_at.astimezone(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
    return SessionSummaryViewModel(
        session_id=session.session_id,
        title=session.title or session.session_id,
        started_at_text=started,
        ended_at_text=ended,
    )


def _recent_device_vm(device: DeviceInfo) -> RecentDeviceViewModel:
    label = device.nickname or device.model_name or device.device_id
    last_seen_raw = str(device.metadata.get("last_seen_at") or "-")
    if last_seen_raw != "-":
        try:
            last_seen_text = datetime.fromisoformat(last_seen_raw).astimezone(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
        except ValueError:
            last_seen_text = last_seen_raw
    else:
        last_seen_text = "-"
    return RecentDeviceViewModel(
        device_id=device.device_id,
        label=label,
        support_text=device.support_level,
        last_seen_text=last_seen_text,
    )
