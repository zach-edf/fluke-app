from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from statistics import median
import threading

from apps.desktop.viewmodels import (
    DeviceMemorySessionViewModel,
    DiscoveryViewModel,
    HomeViewModel,
    LiveReadingViewModel,
    RecentDeviceViewModel,
    ScannedDeviceViewModel,
    SessionCompareViewModel,
    SessionMarkerViewModel,
    SessionContextViewModel,
    SessionSegmentViewModel,
    SettingsViewModel,
    SessionSummaryViewModel,
    SessionViewModel,
    WorkflowDefinitionViewModel,
    WorkflowRunSummaryViewModel,
    WorkflowStepViewModel,
    WorkflowViewModel,
)
from fluke_app import (
    ExportService,
    SessionRecorder,
    WorkflowRunner,
    build_logging_session_previews,
    clear_logging_data,
    default_workflow_directory,
    download_logging_data,
    import_logging_sessions,
    load_workflow_catalog,
    new_session,
    read_logging_config,
    read_logging_status,
    write_logging_config,
)
from fluke_app.export_service import SessionCsvExporter, SessionJsonExporter
from fluke_core.enums import (
    MeasurementType,
    ReadingStatus,
    WorkflowInteractionMode,
    WorkflowRunResult,
    WorkflowStepResultStatus,
)
from fluke_core.models.marker import SessionMarker
from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_core.models.session import Session
from fluke_core.models.workflow import (
    WorkflowCaptureSettings,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunState,
    WorkflowStep,
    WorkflowStepResult,
)
from fluke_core.services.statistics import summarize_readings

_UNCHANGED = object()
_UNKNOWN_REPLAY_THRESHOLD = 5
_REPLAY_UNIT_SCALES: dict[str, tuple[tuple[str, float], ...]] = {
    "voltage": (("uV", 1e-6), ("mV", 1e-3), ("V", 1.0), ("kV", 1e3)),
    "current": (("uA", 1e-6), ("mA", 1e-3), ("A", 1.0)),
    "resistance": (("ohm", 1.0), ("kOhm", 1e3), ("MOhm", 1e6)),
    "capacitance": (("pF", 1e-12), ("nF", 1e-9), ("uF", 1e-6), ("mF", 1e-3), ("F", 1.0)),
    "frequency": (("Hz", 1.0), ("kHz", 1e3), ("MHz", 1e6)),
}


@dataclass(frozen=True, slots=True)
class _ReplayDescriptor:
    context_id: str
    label: str
    normalization_key: str | None
    channel_role: str = "primary"
    is_unknown: bool = False


@dataclass(slots=True)
class _ReplayGroup:
    context_id: str
    label: str
    display_text: str
    readings: list[Reading]
    normalization_key: str | None
    display_unit: str
    total_count: int
    numeric_count: int


@dataclass(frozen=True, slots=True)
class _DerivedSegment:
    segment_id: str
    segment_index: int
    context_id: str
    label: str
    normalization_key: str | None
    measurement_type: str
    unit: str
    mode: str
    start_utc: datetime
    end_utc: datetime
    readings: tuple[Reading, ...]


@dataclass(slots=True)
class _WorkflowCaptureRuntime:
    step_id: str | None = None
    state: str = "idle"
    hint_text: str = ""
    pending_reading: Reading | None = None
    samples: deque[Reading] | None = None
    countdown_deadline: datetime | None = None

    def __post_init__(self) -> None:
        if self.samples is None:
            self.samples = deque(maxlen=64)


class AppPresenter:
    def __init__(
        self,
        device_manager: object,
        store: object,
        app_version: str = "0.1.0",
        export_directory: str | Path = "exports",
        device_operation_timeout_s: float = 10.0,
        auto_reconnect_attempts: int = 3,
        auto_reconnect_delay_s: float = 1.5,
        workflow_catalog: object | None = None,
        workflow_extra_paths: tuple[str | Path, ...] = (),
    ) -> None:
        self._device_manager = device_manager
        self._store = store
        self._app_version = app_version
        self._export_directory = Path(export_directory)
        self._device_operation_timeout_s = device_operation_timeout_s
        self._recorder = SessionRecorder(store.sessions, store.readings, store.markers)
        self._export_service = ExportService(
            store.sessions,
            store.readings,
            store.markers,
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
        self._workflow_directory = default_workflow_directory()
        self._workflow_extra_paths = tuple(Path(path) for path in workflow_extra_paths)
        self._workflow_catalog = workflow_catalog or load_workflow_catalog(
            self._workflow_directory,
            extra_paths=self._workflow_extra_paths,
        )
        self._workflow_runner = WorkflowRunner(
            self._workflow_catalog,
            store.workflow_runs,
            store.workflow_step_results,
        )
        self._workflow = WorkflowViewModel()
        self._workflow_status_message = "Select a workflow to review the steps."
        self._workflow_owned_session_id: str | None = None
        self._workflow_capture = _WorkflowCaptureRuntime()
        self._current_device: DeviceInfo | None = None
        self._device_memory_cache: dict[str, object] | None = None
        self._last_completed_session_id: str | None = None
        self._live_readings: deque[Reading] = deque(maxlen=5000)
        self._raw_notifications: deque[dict[str, object]] = deque(maxlen=5000)
        self._live_markers: list[SessionMarker] = []
        self._live_context_key: tuple[str, ...] | None = None
        self._live_chart_mode = "rolling_30s"
        self._live_segment_started_at: datetime | None = None
        self._last_reading_time: datetime | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._auto_reconnect_attempts = max(0, int(auto_reconnect_attempts))
        self._auto_reconnect_delay_s = max(0.0, float(auto_reconnect_delay_s))
        self._auto_reconnect_task: asyncio.Task[None] | None = None
        self._alert_high: float | None = None
        self._alert_low: float | None = None
        self._active_alert_signature: str | None = None
        self._alert_event_id = 0
        self._device_manager.subscribe_readings(self._recorder.on_reading)
        self._device_manager.subscribe_readings(self.on_reading)
        self._device_manager.subscribe_notifications(self.on_notification)
        self._device_manager.subscribe_connection_diagnostics(self._on_connection_diagnostics)
        self._device_manager.subscribe_disconnects(self._on_device_disconnected)
        self.refresh_recent_devices()
        self.refresh_recent_sessions()
        self.refresh_workflows()

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

    def workflow_view_model(self) -> WorkflowViewModel:
        with self._lock:
            return replace(self._workflow)

    async def scan_devices(self, timeout_s: float = 5.0) -> tuple[ScannedDeviceViewModel, ...]:
        self._remember_running_loop()
        self._set_home_busy(True)
        self._set_discovery_busy(is_scanning=True)
        self._set_discovery(status_text="Scanning...")
        try:
            devices = await self._device_manager.scan(timeout_s=timeout_s)
            scanned = tuple(_device_vm(device) for device in devices)
            self._set_discovery(
                status_text=f"Found {len(scanned)} device(s)" if scanned else "No devices found",
                devices=scanned,
                selected_device_id=scanned[0].device_id if scanned else None,
            )
            self._report_message(f"Scan complete: {len(scanned)} device(s).")
            return scanned
        finally:
            self._set_discovery_busy(is_scanning=False)
            self._set_home_busy(False)

    async def connect_device(self, device_id: str | None = None, profile_id: str | None = None) -> DeviceInfo:
        self._remember_running_loop()
        self._cancel_auto_reconnect()
        target_device_id = device_id or self._discovery.selected_device_id
        if not target_device_id:
            raise RuntimeError("Select a device before connecting.")

        self._set_home_busy(True)
        self._set_discovery_busy(is_connecting=True)
        try:
            self._set_connecting_state(target_device_id)
            try:
                device = await self._device_manager.establish_session(target_device_id, profile_id=profile_id)
            except Exception as exc:
                status = self._device_manager.latest_connection_diagnostics()
                message = str(exc)
                if status is not None:
                    message = status.message
                    if status.last_error_text and status.last_error_text not in message:
                        message = f"{message} Last error: {status.last_error_text}"
                self._set_disconnected_state(
                    connection_text="Disconnected",
                    live_status_text="Disconnected",
                    discovery_status_text=f"Connection failed for {target_device_id}.",
                    diagnostics_text=message,
                    connection_health="error",
                )
                raise RuntimeError(message) from exc

            label = device.nickname or device.model_name or device.device_id
            self._store.upsert_device(device)
            self._set_connected_pending_stream_state(device)
            self.refresh_recent_devices()

            with self._lock:
                self._live = replace(self._live, status_text="Streaming")
                self._discovery = replace(self._discovery, status_text=f"Connected to {label}")
                self._settings = replace(self._settings, diagnostics_text=f"Connected to {label}; BLE stream active.")
                self._home = replace(self._home, message_text=f"Connected to {label}.")

            self.refresh_recent_sessions()
            return device
        finally:
            self._set_discovery_busy(is_connecting=False)
            self._set_home_busy(False)

    async def reconnect_last_device(self) -> DeviceInfo:
        self._remember_running_loop()
        self._cancel_auto_reconnect()
        self._set_home_busy(True)
        try:
            recent = self._store.devices.list_recent(limit=1)
            if not recent:
                raise RuntimeError("No recent device is stored yet.")
            last = recent[0]
            self.select_device(last.device_id)
            return await self.connect_device(device_id=last.device_id, profile_id=last.profile_id or None)
        finally:
            self._set_home_busy(False)

    async def disconnect_device(self) -> None:
        self._remember_running_loop()
        self._cancel_auto_reconnect()
        self._set_home_busy(True)
        if self._workflow_runner.active_state() is not None:
            self._workflow_runner.cancel()
            self._workflow_owned_session_id = None
            self._workflow_status_message = "Workflow cancelled because the device disconnected."
        try:
            if self._recorder.active_session() is not None:
                self.stop_logging()
            await self._device_manager.disconnect()
            self._set_disconnected_state(
                connection_text="Disconnected",
                live_status_text="Disconnected",
                discovery_status_text="Disconnected",
                diagnostics_text="Disconnected.",
            )
            self.refresh_workflows()
        finally:
            self._set_home_busy(False)

    def _on_device_disconnected(self) -> None:
        status = self._device_manager.latest_connection_diagnostics()
        reconnect_failed = bool(status is not None and status.is_recovery)
        detail = "Device disconnected unexpectedly. Check that the meter is powered on and in range."
        if status is not None:
            detail = status.message or status.last_error_text or detail
        self._finalize_unexpected_disconnect(diagnostics_text=detail, reconnect_failed=reconnect_failed)

    def _on_connection_diagnostics(self, status) -> None:
        device = self._current_device
        if status.is_recovery and status.phase in {"recovery_waiting", "direct_connect", "stream_start", "rescan"} and device is not None:
            if status.phase == "recovery_waiting":
                self._record_system_marker("Connection lost. Automatic reconnect started.", label="system")
            if status.phase == "rescan":
                self._set_reconnecting_state(device, status.attempt, max(1, status.total_attempts))
                with self._lock:
                    self._discovery = replace(self._discovery, status_text="Scanning for meter during reconnect...", is_reconnecting=True)
                    self._settings = replace(self._settings, diagnostics_text=status.message)
            else:
                self._set_reconnecting_state(device, max(1, status.attempt), max(1, status.total_attempts))
                with self._lock:
                    self._settings = replace(self._settings, diagnostics_text=status.message)
            return
        if status.is_recovery and status.phase == "recovered":
            if self._current_device is None:
                active = self._device_manager.active_device()
                if active is not None:
                    self._current_device = active
            if self._current_device is not None:
                self._set_reconnected_state(self._current_device)
                self._record_system_marker("Connection restored after automatic reconnect.", label="system")
                self._store.upsert_device(self._current_device)
                self.refresh_recent_devices()
                self.refresh_recent_sessions()

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
            self._live_markers = []
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
                selected_session_id=session.session_id,
            )
        self.refresh_recent_sessions()
        self.select_session(session.session_id)
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
                selected_session_id=session.session_id,
            )
            self._home = replace(self._home, active_session_text=session_label)
        self.refresh_recent_sessions()
        self.select_session(session.session_id)
        return session

    def add_marker(self, note: str, label: str = "note") -> SessionMarker:
        marker = self._recorder.add_marker(note, label=label)
        with self._lock:
            self._live_markers.append(marker)
            self._refresh_live_chart_locked()
            self._live = replace(
                self._live,
                marker_count_text=f"{self._recorder.marker_count()} markers",
            )
        if self.session_view_model().selected_session_id == marker.session_id:
            self.select_session(marker.session_id)
        return marker

    def export_session_csv(self, path: str | Path, session_id: str | None = None) -> str:
        target = self._resolve_export_session_id(session_id)
        export_path = self._resolve_export_path(path, "desktop_session.csv")
        exported = self._export_service.export_csv(target, export_path)
        with self._lock:
            self._session = replace(self._session, export_status_text=f"Raw CSV exported to {exported}")
        return exported

    def export_session_json(self, path: str | Path, session_id: str | None = None) -> str:
        target = self._resolve_export_session_id(session_id)
        export_path = self._resolve_export_path(path, "desktop_session.json")
        exported = self._export_service.export_json(target, export_path)
        with self._lock:
            self._session = replace(self._session, export_status_text=f"Raw JSON exported to {exported}")
        return exported

    def export_analysis_csv(self, path: str | Path, session_id: str | None = None) -> str:
        target = self._resolve_export_session_id(session_id)
        export_path = self._resolve_export_path(path, "desktop_analysis.csv")
        exported = self._export_service.export_analysis_csv(target, export_path)
        with self._lock:
            self._session = replace(self._session, export_status_text=f"Analysis CSV exported to {exported}")
        return exported

    def export_segment_summary_json(self, path: str | Path, session_id: str | None = None) -> str:
        target = self._resolve_export_session_id(session_id)
        export_path = self._resolve_export_path(path, "desktop_segments.json")
        exported = self._export_service.export_segment_summary_json(target, export_path)
        with self._lock:
            self._session = replace(self._session, export_status_text=f"Segment summary JSON exported to {exported}")
        return exported

    def set_device_memory_value_source(self, value_source: str) -> None:
        with self._lock:
            self._session = replace(self._session, device_memory_value_source=str(value_source or "average"))

    async def refresh_device_memory_status(self) -> dict[str, object]:
        self._remember_running_loop()
        if self._recorder.active_session() is not None:
            raise RuntimeError("Stop the active logging session before reading device memory status.")
        device = self._device_manager.active_device()
        if device is None:
            raise RuntimeError("Connect to a device before reading device memory status.")
        if not self._device_has_capability("device_memory_download"):
            raise RuntimeError("The connected device does not expose saved-memory status.")

        self._set_home_busy(True)
        with self._lock:
            self._session = replace(self._session, device_memory_status_text="Reading device memory status...")
            self._settings = replace(
                self._settings,
                diagnostics_text=f"Reading device memory status from {device.device_id}...",
            )
        try:
            status_report = await read_logging_status(self._device_manager.ble_adapter(), device.device_id)
            self._apply_device_memory_status_to_session(status_report)
            with self._lock:
                self._settings = replace(
                    self._settings,
                    diagnostics_text=(
                        f"Read device memory status from {device.device_id}: "
                        f"{status_report['bytes_logged']} byte(s), {status_report['blocks_logged']} block(s), "
                        f"state={status_report['state_label']}."
                    ),
                )
            return status_report
        finally:
            self._set_home_busy(False)

    async def browse_device_memory(self, value_source: str = "average") -> dict[str, object]:
        self._remember_running_loop()
        if self._recorder.active_session() is not None:
            raise RuntimeError("Stop the active logging session before browsing device memory.")
        device = self._device_manager.active_device()
        if device is None:
            raise RuntimeError("Connect to a device before browsing device memory.")
        if not self._device_has_capability("device_memory_download"):
            raise RuntimeError("The connected device does not expose saved-memory download.")

        self._set_home_busy(True)
        with self._lock:
            self._session = replace(
                self._session,
                device_memory_value_source=value_source,
                device_memory_status_text="Downloading device memory...",
                export_status_text="Browsing device memory...",
            )
            self._settings = replace(
                self._settings,
                diagnostics_text=f"Downloading saved device-memory sessions from {device.device_id}...",
            )
        try:
            download_report = await download_logging_data(self._device_manager.ble_adapter(), device.device_id)
            if "decode_error" in download_report:
                raise RuntimeError(f"Could not decode downloaded device-memory payload: {download_report['decode_error']}")
            decoded_sessions = [
                session for session in download_report.get("decoded_sessions", []) if isinstance(session, dict)
            ]
            previews_raw = build_logging_session_previews(
                session_repo=self._store.sessions,
                device_id=device.device_id,
                decoded_sessions=decoded_sessions,
            )
            preview_lookup = {
                str(preview["preview_id"]): session
                for preview, session in zip(previews_raw, decoded_sessions, strict=True)
            }
            self._device_memory_cache = {
                "device_id": device.device_id,
                "value_source": value_source,
                "download_report": download_report,
                "previews": previews_raw,
                "preview_lookup": preview_lookup,
            }
            status_report = _logging_status_summary_from_download_report(download_report)
            self._apply_device_memory_status_to_session(
                status_report,
                preview_summary=f"{len(previews_raw)} session(s) available for import.",
                previews=tuple(_device_memory_session_vm(preview) for preview in previews_raw),
                value_source=value_source,
            )
            with self._lock:
                self._settings = replace(
                    self._settings,
                    diagnostics_text=(
                        f"Browsed device memory for {device.device_id}: "
                        f"{len(previews_raw)} decoded session(s), {download_report.get('downloaded_bytes', 0)} byte(s) downloaded."
                    ),
                )
            self._report_message(f"Loaded {len(previews_raw)} device-memory session(s).")
            return {
                "download_report": download_report,
                "previews": previews_raw,
            }
        finally:
            self._set_home_busy(False)

    async def import_device_memory(self, value_source: str = "average") -> dict[str, object]:
        browse_report = await self.browse_device_memory(value_source=value_source)
        import_report = await self.import_all_device_memory(value_source=value_source)
        return {
            "download_report": browse_report["download_report"],
            "import_report": import_report["import_report"],
            **({"clear_report": import_report["clear_report"]} if "clear_report" in import_report else {}),
        }

    async def import_selected_device_memory(
        self,
        preview_ids: tuple[str, ...] | list[str],
        *,
        value_source: str | None = None,
    ) -> dict[str, object]:
        return await self._import_cached_device_memory(
            preview_ids=tuple(str(item) for item in preview_ids if item),
            value_source=value_source,
            clear_after_import=False,
        )

    async def import_all_device_memory(
        self,
        *,
        value_source: str | None = None,
        clear_after_import: bool = False,
    ) -> dict[str, object]:
        return await self._import_cached_device_memory(
            preview_ids=None,
            value_source=value_source,
            clear_after_import=clear_after_import,
        )

    async def clear_device_memory(self) -> dict[str, object]:
        self._remember_running_loop()
        if self._recorder.active_session() is not None:
            raise RuntimeError("Stop the active logging session before clearing device memory.")
        device = self._device_manager.active_device()
        if device is None:
            raise RuntimeError("Connect to a device before clearing device memory.")
        if not self._device_has_capability("device_memory_clear"):
            raise RuntimeError("The connected device does not expose device-memory erase.")

        self._set_home_busy(True)
        with self._lock:
            self._session = replace(self._session, device_memory_status_text="Clearing device memory...")
        try:
            report = await clear_logging_data(self._device_manager.ble_adapter(), device.device_id)
            self._device_memory_cache = None
            self._apply_device_memory_status_to_session(
                report["status_after"],
                preview_summary="Device memory cleared.",
                previews=(),
            )
            with self._lock:
                self._session = replace(
                    self._session,
                    export_status_text="Cleared device memory.",
                )
                self._settings = replace(
                    self._settings,
                    diagnostics_text=(
                        f"Cleared device memory on {device.device_id}: "
                        f"{report['status_after']['bytes_logged']} byte(s), "
                        f"{report['status_after']['blocks_logged']} block(s) remain."
                    ),
                )
            self._report_message("Cleared device memory.")
            return report
        finally:
            self._set_home_busy(False)

    def export_raw_fixture_capture(self, path: str | Path | None = None, *, max_frames: int = 200) -> str:
        device = self._device_manager.active_device()
        if device is None:
            raise RuntimeError("Connect to a device before exporting a raw fixture capture.")
        frames = list(self._raw_notifications)[-max(1, int(max_frames)) :]
        if not frames:
            raise RuntimeError("No raw notification frames have been buffered yet.")
        export_path = self._resolve_export_path(
            path or (self._export_directory / "fixtures" / f"{device.device_id}-fixture.json"),
            f"{device.device_id}-fixture.json",
        )
        export_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "device": {
                "device_id": device.device_id,
                "model_name": device.model_name,
                "profile_id": device.profile_id,
                "family_id": device.family_id,
                "variant_id": device.variant_id,
                "support_level": device.support_level,
                "capabilities": list(device.capabilities),
            },
            "services": _json_safe(self._device_manager.active_runtime_services()),
            "frame_count": len(frames),
            "frames": frames,
            "parsed_readings": [reading.as_dict() for reading in list(self._live_readings)[-max(1, int(max_frames)) :]],
        }
        export_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        with self._lock:
            self._settings = replace(
                self._settings,
                fixture_status_text=f"Saved raw fixture capture to {export_path}",
            )
        return str(export_path)

    async def read_device_logging_config(self) -> dict[str, object]:
        self._remember_running_loop()
        if self._recorder.active_session() is not None:
            raise RuntimeError("Stop the active logging session before reading logging settings.")
        device = self._device_manager.active_device()
        if device is None:
            raise RuntimeError("Connect to a device before reading logging settings.")
        if not self._device_has_capability("device_logging_config"):
            raise RuntimeError("The connected device does not expose logging settings.")

        self._set_home_busy(True)
        with self._lock:
            self._live = replace(self._live, logging_status_text="Reading logging settings...")
        try:
            report = await read_logging_config(self._device_manager.ble_adapter(), device.device_id)
            self._apply_logging_config_to_live(report)
            with self._lock:
                self._settings = replace(
                    self._settings,
                    diagnostics_text=(
                        f"Read logging settings from {device.device_id}: "
                        f"interval={report['interval_seconds']}s, duration={report['duration_seconds']}s."
                    ),
                )
            self._report_message("Read device logging settings.")
            return report
        finally:
            self._set_home_busy(False)

    async def apply_device_logging_config(self, *, interval_seconds: int, duration_seconds: int) -> dict[str, object]:
        self._remember_running_loop()
        if self._recorder.active_session() is not None:
            raise RuntimeError("Stop the active logging session before applying logging settings.")
        device = self._device_manager.active_device()
        if device is None:
            raise RuntimeError("Connect to a device before applying logging settings.")
        if not self._device_has_capability("device_logging_config"):
            raise RuntimeError("The connected device does not expose logging settings.")

        self._set_home_busy(True)
        with self._lock:
            self._live = replace(self._live, logging_status_text="Applying logging settings...")
        try:
            report = await write_logging_config(
                self._device_manager.ble_adapter(),
                device.device_id,
                interval_seconds=interval_seconds,
                duration_seconds=duration_seconds,
                read_before=True,
                read_after=True,
            )
            if not report.get("write_ok"):
                raise RuntimeError(str(report.get("write_error") or "Failed to write logging settings."))
            applied = report.get("read_after") or {
                "interval_seconds": interval_seconds,
                "duration_seconds": duration_seconds,
            }
            self._apply_logging_config_to_live(applied)
            with self._lock:
                self._settings = replace(
                    self._settings,
                    diagnostics_text=(
                        f"Applied logging settings to {device.device_id}: "
                        f"interval={applied['interval_seconds']}s, duration={applied['duration_seconds']}s."
                    ),
                )
            self._report_message("Updated device logging settings.")
            return report
        finally:
            self._set_home_busy(False)

    async def _import_cached_device_memory(
        self,
        *,
        preview_ids: tuple[str, ...] | None,
        value_source: str | None,
        clear_after_import: bool,
    ) -> dict[str, object]:
        self._remember_running_loop()
        if self._recorder.active_session() is not None:
            raise RuntimeError("Stop the active logging session before importing device memory.")
        device = self._device_manager.active_device()
        if device is None:
            raise RuntimeError("Connect to a device before importing device memory.")
        if not self._device_has_capability("device_memory_download"):
            raise RuntimeError("The connected device does not expose saved-memory download.")

        selected_value_source = str(value_source or self._session.device_memory_value_source or "average")
        cache = self._device_memory_cache
        if (
            cache is None
            or cache.get("device_id") != device.device_id
            or cache.get("value_source") != selected_value_source
        ):
            if preview_ids is not None:
                raise RuntimeError("Browse device memory before importing selected sessions.")
            await self.browse_device_memory(selected_value_source)
            cache = self._device_memory_cache

        if cache is None:
            raise RuntimeError("Device-memory cache is not available.")

        preview_lookup = cache.get("preview_lookup")
        if not isinstance(preview_lookup, dict):
            raise RuntimeError("Device-memory cache is incomplete.")

        selected_sessions: list[dict[str, object]] = []
        if preview_ids is None:
            selected_sessions = [session for session in preview_lookup.values() if isinstance(session, dict)]
        else:
            for preview_id in preview_ids:
                session = preview_lookup.get(preview_id)
                if isinstance(session, dict):
                    selected_sessions.append(session)
        if not selected_sessions:
            raise RuntimeError("No device-memory sessions selected for import.")

        self._set_home_busy(True)
        with self._lock:
            self._session = replace(self._session, export_status_text="Importing device-memory sessions...")
        try:
            import_report = import_logging_sessions(
                device_repo=self._store.devices,
                session_repo=self._store.sessions,
                reading_repo=self._store.readings,
                device_id=device.device_id,
                decoded_sessions=selected_sessions,
                profile_id=device.profile_id or "fluke_376fc",
                value_source=selected_value_source,
            )
            self.refresh_recent_sessions()
            imported_sessions = import_report["imported_sessions"]
            if imported_sessions:
                newest = max(imported_sessions, key=lambda item: str(item["started_at"]))
                self.select_session(str(newest["session_id"]))

            clear_report: dict[str, object] | None = None
            if clear_after_import:
                clear_report = await clear_logging_data(self._device_manager.ble_adapter(), device.device_id)
                self._device_memory_cache = None
                self._apply_device_memory_status_to_session(
                    clear_report["status_after"],
                    preview_summary="Device memory cleared after import.",
                    previews=(),
                    value_source=selected_value_source,
                )
            else:
                refreshed_previews = build_logging_session_previews(
                    session_repo=self._store.sessions,
                    device_id=device.device_id,
                    decoded_sessions=[session for session in preview_lookup.values() if isinstance(session, dict)],
                )
                self._device_memory_cache = {
                    **cache,
                    "previews": refreshed_previews,
                }
                status_report = _logging_status_summary_from_download_report(cache.get("download_report", {}))
                self._apply_device_memory_status_to_session(
                    status_report,
                    preview_summary=f"{len(refreshed_previews)} session(s) loaded from device memory.",
                    previews=tuple(_device_memory_session_vm(preview) for preview in refreshed_previews),
                    value_source=selected_value_source,
                )

            summary = (
                f"Imported {import_report['imported_count']} device-memory session(s)"
                f" and skipped {import_report['skipped_count']} duplicate(s)."
            )
            if clear_after_import:
                summary = f"{summary[:-1]} before clearing the meter."
            with self._lock:
                self._session = replace(self._session, export_status_text=summary)
                self._settings = replace(
                    self._settings,
                    diagnostics_text=(
                        f"Device-memory import complete for {device.device_id}: "
                        f"{import_report['imported_count']} imported, "
                        f"{import_report['skipped_count']} skipped."
                    ),
                )
            self._report_message(summary)
            response: dict[str, object] = {"import_report": import_report}
            if clear_report is not None:
                response["clear_report"] = clear_report
            return response
        finally:
            self._set_home_busy(False)

    def export_workflow_report(self, path: str | Path, run_id: str | None = None) -> str:
        target = self._resolve_export_workflow_run_id(run_id)
        details = self._workflow_run_details(target)
        if details is None:
            raise RuntimeError(f"Unknown workflow run {target!r}.")
        definition, run, results, session = details
        export_path = self._resolve_export_path(path, f"workflow-run-{target}.md")
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(
            _workflow_report_text(definition, run, results, session_title=None if session is None else (session.title or "")),
            encoding="utf-8",
        )
        return str(export_path)

    def set_export_directory(self, path: str | Path) -> None:
        export_dir = Path(path)
        with self._lock:
            self._export_directory = export_dir
            self._settings = replace(self._settings, export_directory_text=str(export_dir))

    def set_export_status(self, message: str) -> None:
        with self._lock:
            self._session = replace(self._session, export_status_text=message)

    async def shutdown(self) -> None:
        self._remember_running_loop()
        self._cancel_auto_reconnect()
        if self._workflow_runner.active_state() is not None:
            self._workflow_runner.cancel()
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
        selected = self.session_view_model().selected_session_id
        if selected:
            try:
                self.select_session(selected)
                return
            except RuntimeError:
                pass
        if rows:
            self.select_session(rows[0].session_id)
        else:
            with self._lock:
                self._session = replace(
                    self._session,
                    selected_session_id=None,
                    active_title_text="No active session",
                    reading_count_text="0 readings",
                    selected_context_id=None,
                    selected_context_label="",
                    available_contexts=(),
                    available_compare_sessions=(),
                    selected_summary_text="Min - | Max - | Avg -",
                    compare_session_id=None,
                    compare_session_label="",
                    compare_summary_text="",
                    selected_unit_text="",
                    selected_session_notes="",
                    selected_markers=(),
                    chart_points=(),
                    compare_chart_points=(),
                    marker_points=(),
                )

    def refresh_workflows(self, limit: int = 10) -> None:
        definitions = self._workflow_catalog.list()
        definition_rows = tuple(_workflow_definition_vm(definition) for definition in definitions)
        active_state = self._workflow_runner.active_state()
        current_workflow = self.workflow_view_model()
        selected_id = current_workflow.selected_workflow_id
        selected_run_id = current_workflow.selected_run_id

        if active_state is not None:
            selected_id = active_state.definition.workflow_id
            selected_run_id = active_state.run.run_id
        elif selected_id is None and definitions:
            selected_id = definitions[0].workflow_id

        recent_run_models = self._workflow_runner.list_recent_runs(limit=limit)
        recent_runs = tuple(_workflow_run_vm(run) for run in recent_run_models)
        recent_run_ids = {run.run_id for run in recent_run_models}
        if selected_run_id not in recent_run_ids:
            selected_run_id = None
        if selected_run_id is None and selected_id is not None:
            selected_recent_run = next((run for run in recent_run_models if run.workflow_id == selected_id), None)
            selected_run_id = None if selected_recent_run is None else selected_recent_run.run_id

        selected_recent_run = next((run for run in recent_run_models if run.run_id == selected_run_id), None)
        if selected_recent_run is not None:
            selected_id = selected_recent_run.workflow_id

        selected_definition = None if selected_id is None else self._workflow_catalog.get(selected_id)
        if selected_definition is None and selected_recent_run is not None:
            selected_definition = self._workflow_catalog.get(selected_recent_run.workflow_id)
            selected_id = None if selected_definition is None else selected_definition.workflow_id

        current_title = "No workflow selected"
        current_description = ""
        progress_text = "0/0 steps"
        current_step_title = "No active step"
        current_instruction = ""
        current_requirement = ""
        current_interaction_mode = ""
        capture_state_text = ""
        capture_hint_text = ""
        active_session_text = "No workflow session"
        latest_capture_text = "No captured step yet"
        run_result_text = ""
        selected_run_summary_text = "No workflow run selected"
        report_text = ""
        completed_steps: tuple[WorkflowStepViewModel, ...] = ()
        is_running = active_state is not None and active_state.run.result == WorkflowRunResult.IN_PROGRESS
        primary_action_text = "Complete Step"
        can_continue_capture = False
        can_retake_capture = False

        if selected_definition is not None:
            current_title = selected_definition.title
            current_description = selected_definition.description
            progress_text = f"0/{len(selected_definition.steps)} steps"

        if active_state is not None:
            selected_definition = active_state.definition
            current_title = selected_definition.title
            current_description = selected_definition.description
            progress_text = active_state.progress_text
            current_step = active_state.current_step
            current_step_title = "Workflow complete" if current_step is None else current_step.title
            current_instruction = "" if current_step is None else current_step.instruction
            current_requirement = "" if current_step is None else _workflow_requirement_text(current_step)
            current_interaction_mode = "" if current_step is None else _workflow_interaction_mode_text(current_step)
            active_session_text = active_state.run.session_id
            latest_capture_text = _latest_capture_text(active_state.completed_steps)
            run_result_text = active_state.run.result.value.replace("_", " ").title()
            completed_steps = tuple(_workflow_step_vm(result, selected_definition) for result in active_state.completed_steps)
            if current_step is not None:
                if current_step.interaction_mode == WorkflowInteractionMode.COUNTDOWN_CAPTURE:
                    primary_action_text = "Start Countdown"
                elif current_step.requires_reading:
                    primary_action_text = "Capture Now"
                elif current_step.interaction_mode == WorkflowInteractionMode.OBSERVE_AND_CONFIRM:
                    primary_action_text = "Confirm Step"
                capture_state_text = _capture_state_text(self._workflow_capture.state)
                capture_hint_text = self._workflow_capture.hint_text
                can_continue_capture = self._workflow_capture.pending_reading is not None and current_step.requires_reading
                can_retake_capture = can_continue_capture
                if self._workflow_capture.pending_reading is not None:
                    latest_capture_text = f"Pending capture: {self._workflow_capture.pending_reading.display_text}"
            session = self._store.sessions.get(active_state.run.session_id)
            selected_run_summary_text = _workflow_run_summary_text(
                active_state.run,
                session_title=None if session is None else (session.title or ""),
                viewing_active=True,
            )
            report_text = _workflow_report_text(
                selected_definition,
                active_state.run,
                active_state.completed_steps,
                session_title=None if session is None else (session.title or ""),
            )
        elif selected_definition is not None and selected_recent_run is not None:
            results = tuple(self._workflow_runner.results_for_run(selected_recent_run.run_id))
            progress_text = f"{len(results)}/{len(selected_definition.steps)} steps"
            current_step_title, current_instruction, current_requirement = _historical_workflow_step_summary(
                selected_definition,
                selected_recent_run,
                results,
            )
            active_session_text = selected_recent_run.session_id
            latest_capture_text = _latest_capture_text(results)
            run_result_text = selected_recent_run.result.value.replace("_", " ").title()
            completed_steps = tuple(_workflow_step_vm(result, selected_definition) for result in results)
            session = self._store.sessions.get(selected_recent_run.session_id)
            selected_run_summary_text = _workflow_run_summary_text(
                selected_recent_run,
                session_title=None if session is None else (session.title or ""),
            )
            report_text = _workflow_report_text(
                selected_definition,
                selected_recent_run,
                results,
                session_title=None if session is None else (session.title or ""),
            )
        elif selected_definition is not None:
            report_text = _workflow_definition_report_text(selected_definition)

        with self._lock:
            self._workflow = WorkflowViewModel(
                status_text=self._workflow_status_message,
                selected_workflow_id=selected_id,
                selected_run_id=selected_run_id,
                workflows=definition_rows,
                current_title_text=current_title,
                current_description_text=current_description,
                progress_text=progress_text,
                current_step_title=current_step_title,
                current_instruction_text=current_instruction,
                current_requirement_text=current_requirement,
                current_interaction_mode_text=current_interaction_mode,
                capture_state_text=capture_state_text,
                capture_hint_text=capture_hint_text,
                active_session_text=active_session_text,
                latest_capture_text=latest_capture_text,
                run_result_text=run_result_text,
                selected_run_summary_text=selected_run_summary_text,
                report_text=report_text,
                is_running=is_running,
                primary_action_text=primary_action_text,
                can_continue_capture=can_continue_capture,
                can_retake_capture=can_retake_capture,
                completed_steps=completed_steps,
                recent_runs=recent_runs,
            )

    def report_error(self, message: str) -> None:
        with self._lock:
            self._home = replace(
                self._home,
                message_text=message,
                connection_text=f"Error: {message}",
                connection_health="error",
            )
            self._discovery = replace(self._discovery, status_text=f"Error: {message}")
            self._session = replace(self._session, export_status_text=message)
            self._live = replace(self._live, status_text="Error", connection_health="error")
            self._settings = replace(self._settings, diagnostics_text=message)
            self._workflow = replace(self._workflow, status_text=message)
        self._workflow_status_message = message

    def select_device(self, device_id: str | None) -> None:
        with self._lock:
            self._discovery = replace(self._discovery, selected_device_id=device_id)

    def select_workflow(self, workflow_id: str | None) -> None:
        with self._lock:
            self._workflow = replace(self._workflow, selected_workflow_id=workflow_id, selected_run_id=None)
        if workflow_id is not None:
            definition = self._workflow_catalog.get(workflow_id)
            if definition is not None:
                self._workflow_status_message = f"Ready to start {definition.title}."
        self.refresh_workflows()

    def select_workflow_run(self, run_id: str | None) -> None:
        workflow_id = None
        if run_id is not None:
            run = self._store.workflow_runs.get(run_id)
            if run is None:
                raise RuntimeError(f"Unknown workflow run {run_id!r}.")
            workflow_id = run.workflow_id
        with self._lock:
            self._workflow = replace(
                self._workflow,
                selected_workflow_id=workflow_id if workflow_id is not None else self._workflow.selected_workflow_id,
                selected_run_id=run_id,
            )
        self.refresh_workflows()

    def start_workflow(self, workflow_id: str | None = None) -> str:
        target = workflow_id or self.workflow_view_model().selected_workflow_id
        if target is None:
            raise RuntimeError("Select a workflow before starting it.")
        definition = self._workflow_catalog.get(target)
        if definition is None:
            raise RuntimeError(f"Unknown workflow {target!r}.")
        session = self._recorder.active_session()
        owns_session = False
        if session is None:
            session_id = self.start_logging(
                title=f"Workflow - {definition.title}",
                notes=f"Guided workflow run for {definition.title}.",
                tags=["workflow", definition.workflow_id],
            )
            session = self._store.sessions.get(session_id)
            owns_session = True
        if session is None:
            raise RuntimeError("Workflow could not create or resolve a session.")
        state = self._workflow_runner.start(definition.workflow_id, session.session_id)
        self._reset_workflow_capture_runtime()
        self._workflow_owned_session_id = session.session_id if owns_session else None
        self._workflow_status_message = f"Started {definition.title}."
        self.add_marker(f"Started workflow: {definition.title}", label="workflow")
        self.refresh_workflows()
        return state.run.run_id

    def create_workflow(self, definition: WorkflowDefinition) -> str:
        if not definition.workflow_id.strip():
            raise RuntimeError("Workflow ID is required.")
        if not definition.title.strip():
            raise RuntimeError("Workflow title is required.")
        if not definition.steps:
            raise RuntimeError("Add at least one workflow step.")
        if self._workflow_catalog.get(definition.workflow_id) is not None:
            raise RuntimeError(f"Workflow {definition.workflow_id!r} already exists.")

        seen_step_ids: set[str] = set()
        for step in definition.steps:
            if not step.step_id.strip():
                raise RuntimeError("Each workflow step needs an ID.")
            if step.step_id in seen_step_ids:
                raise RuntimeError(f"Duplicate workflow step ID {step.step_id!r}.")
            if not step.title.strip():
                raise RuntimeError(f"Workflow step {step.step_id!r} is missing a title.")
            if not step.instruction.strip():
                raise RuntimeError(f"Workflow step {step.step_id!r} is missing instructions.")
            seen_step_ids.add(step.step_id)

        self._workflow_directory.mkdir(parents=True, exist_ok=True)
        path = self._workflow_directory / f"{definition.workflow_id}.json"
        if path.exists():
            raise RuntimeError(f"Workflow file already exists: {path.name}")

        path.write_text(
            json.dumps(_workflow_definition_payload(definition), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        self._workflow_catalog = load_workflow_catalog(
            self._workflow_directory,
            extra_paths=self._workflow_extra_paths,
        )
        with self._lock:
            self._workflow = replace(
                self._workflow,
                selected_workflow_id=definition.workflow_id,
                selected_run_id=None,
            )
        self._workflow_status_message = f"Created workflow {definition.title}."
        self.refresh_workflows()
        return str(path)

    def complete_workflow_step(self, note: str | None = None) -> str:
        current = self._workflow_runner.active_state()
        if current is None or current.current_step is None:
            raise RuntimeError("Start a workflow before completing steps.")
        step = current.current_step
        if step.interaction_mode == WorkflowInteractionMode.COUNTDOWN_CAPTURE and self._workflow_capture.pending_reading is None:
            deadline = datetime.now(timezone.utc) + timedelta(seconds=step.capture_settings.countdown_s)
            self._workflow_capture.step_id = step.step_id
            self._workflow_capture.state = "settling"
            self._workflow_capture.hint_text = f"Countdown running for {step.capture_settings.countdown_s:.1f}s."
            self._workflow_capture.countdown_deadline = deadline
            self.refresh_workflows()
            return current.run.run_id

        latest = self._workflow_capture.pending_reading or self._device_manager.latest_reading()
        if step.requires_reading:
            latest = self._workflow_runner.validate_reading_for_step(step, latest)
        state = self._workflow_runner.complete_current_step(latest_reading=latest, note=note)
        detail = f"{current.definition.title}: {step.title}"
        if step.requires_reading and latest is not None:
            detail = f"{detail} ({latest.display_text})"
        self.add_marker(detail, label="workflow")
        self._workflow_status_message = f"Completed step {step.title}."
        self._reset_workflow_capture_runtime()
        self._finish_workflow_if_complete(state)
        self.refresh_workflows()
        return state.run.run_id

    def continue_workflow_capture(self, note: str | None = None) -> str:
        if self._workflow_capture.pending_reading is None:
            raise RuntimeError("No captured reading is waiting for confirmation.")
        return self.complete_workflow_step(note=note)

    def retake_workflow_capture(self) -> None:
        current = self._workflow_runner.active_state()
        if current is None or current.current_step is None or not current.current_step.requires_reading:
            raise RuntimeError("No capture step is active.")
        self._workflow_capture.pending_reading = None
        self._workflow_capture.samples.clear()
        self._workflow_capture.countdown_deadline = None
        self._workflow_capture.state = "contact_detected"
        self._workflow_capture.hint_text = "Retake armed. Reacquire a stable reading."
        self._workflow_status_message = f"Retake {current.current_step.title}."
        self.refresh_workflows()

    def skip_workflow_step(self, note: str | None = None) -> str:
        current = self._workflow_runner.active_state()
        if current is None or current.current_step is None:
            raise RuntimeError("Start a workflow before skipping steps.")
        step = current.current_step
        state = self._workflow_runner.skip_current_step(note=note)
        self.add_marker(f"Skipped workflow step: {step.title}", label="workflow")
        self._workflow_status_message = f"Skipped step {step.title}."
        self._reset_workflow_capture_runtime()
        self._finish_workflow_if_complete(state)
        self.refresh_workflows()
        return state.run.run_id

    def cancel_workflow(self) -> str | None:
        run = self._workflow_runner.cancel()
        if run is None:
            return None
        self._workflow_status_message = f"Cancelled workflow {run.workflow_title or run.workflow_id}."
        if self._recorder.active_session() is not None:
            self.add_marker(f"Cancelled workflow: {run.workflow_title or run.workflow_id}", label="workflow")
        if self._workflow_owned_session_id == run.session_id:
            self.stop_logging()
        self._workflow_owned_session_id = None
        self._reset_workflow_capture_runtime()
        self.refresh_workflows()
        return run.run_id

    def select_session(self, session_id: str) -> None:
        session = self._store.sessions.get(session_id)
        if session is None:
            raise RuntimeError(f"Unknown session {session_id!r}.")
        readings = self._store.readings.list_for_session(session_id)
        markers = self._store.markers.list_for_session(session_id)
        current_session = self.session_view_model()
        replay_groups = _build_session_replay_groups(readings)
        derived_segments = _derive_mode_segments(readings)
        compare_options = tuple(
            _session_compare_vm(item)
            for item in self._store.sessions.list_recent(limit=25)
            if item.session_id != session_id
        )
        same_session = current_session.selected_session_id == session_id
        selected_context_id = current_session.selected_context_id if same_session else None
        selected_replay_channel = current_session.selected_replay_channel if same_session else "primary"
        selected_axis_mode = current_session.selected_axis_mode if same_session else "elapsed"
        selected_segment_id = current_session.selected_segment_id if same_session else None
        selected_compare_session_id = current_session.compare_session_id if same_session else None
        if selected_axis_mode not in {"elapsed", "utc", "by_segment"}:
            selected_axis_mode = "elapsed"
        if selected_context_id is not None and selected_context_id not in {group.context_id for group in replay_groups}:
            selected_context_id = None
        if selected_compare_session_id not in {item.session_id for item in compare_options}:
            selected_compare_session_id = None
        available_replay_channels = tuple(
            channel
            for channel in ("primary", "secondary")
            if any(_replay_descriptor(reading).channel_role == channel for reading in readings)
        )
        if selected_replay_channel not in {"primary", "secondary"}:
            selected_replay_channel = "primary"
        if selected_replay_channel not in available_replay_channels and available_replay_channels:
            selected_replay_channel = available_replay_channels[0]
        if selected_context_id is None and available_replay_channels and len(available_replay_channels) > 1:
            selected_context_id = next(
                (group.context_id for group in replay_groups if group.context_id.startswith(f"{selected_replay_channel}\x1f")),
                selected_context_id,
            )
        if selected_context_id is None and replay_groups and (not same_session or not current_session.available_contexts):
            if len(replay_groups) > 1:
                selected_context_id = replay_groups[0].context_id

        selected_group: _ReplayGroup | None = None
        primary_stats = None
        matching_segments: list[_DerivedSegment] = []
        if selected_context_id is None and len(replay_groups) > 1:
            filtered_readings = []
            filtered_markers = markers
            selected_summary_text = (
                f"Mixed measurement session across {len(replay_groups)} replay views. "
                "Select a measurement view to chart readings."
            )
            unit_text = ""
            context_label = "All Measurements"
            reading_count_text = f"{len(readings)} readings"
        else:
            selected_group = (
                replay_groups[0]
                if selected_context_id is None and replay_groups
                else next((group for group in replay_groups if group.context_id == selected_context_id), None)
            )
            filtered_readings = [] if selected_group is None else selected_group.readings
            filtered_markers = markers if selected_group is None else _markers_for_context(
                readings,
                markers,
                selected_group.context_id,
            )
            primary_stats = summarize_readings(filtered_readings)
            selected_summary_text = _summary_text(primary_stats)
            unit_text = next((reading.unit for reading in filtered_readings if reading.unit), "")
            context_label = "" if selected_group is None else selected_group.label
            reading_count_text = f"{len(filtered_readings)} readings"
            matching_segments = [] if selected_group is None else [
                segment for segment in derived_segments if segment.context_id == selected_group.context_id
            ]
            if selected_axis_mode == "by_segment" and matching_segments:
                segment_ids = {segment.segment_id for segment in matching_segments}
                if selected_segment_id not in segment_ids:
                    selected_segment_id = matching_segments[0].segment_id
                active_segment = next((segment for segment in matching_segments if segment.segment_id == selected_segment_id), None)
                if active_segment is not None:
                    filtered_readings = list(active_segment.readings)
                    if active_segment.normalization_key is not None and unit_text:
                        filtered_readings = _normalize_readings_to_unit(
                            filtered_readings,
                            active_segment.normalization_key,
                            unit_text,
                        )
                    filtered_markers = [
                        marker
                        for marker in filtered_markers
                        if active_segment.start_utc <= marker.timestamp_utc <= active_segment.end_utc
                    ]
                    primary_stats = summarize_readings(filtered_readings)
                    selected_summary_text = f"{_summary_text(primary_stats)} | {active_segment.label} segment"
                    context_label = f"{selected_group.label} | {active_segment.label}"
                    reading_count_text = f"{len(filtered_readings)} readings"
            else:
                selected_segment_id = None

        chart_axis_mode = "elapsed" if selected_axis_mode == "by_segment" else selected_axis_mode
        points = tuple(_chart_points(filtered_readings, axis_mode=chart_axis_mode))
        compare_points: tuple[tuple[float, float], ...] = ()
        compare_summary_text = ""
        compare_session_label = ""
        if selected_compare_session_id is not None:
            compare_session = self._store.sessions.get(selected_compare_session_id)
            if compare_session is None:
                selected_compare_session_id = None
            else:
                compare_session_label = compare_session.title or compare_session.session_id
                if selected_axis_mode == "by_segment":
                    compare_summary_text = "Comparison unavailable while viewing a single segment."
                elif selected_group is None or primary_stats is None:
                    compare_summary_text = "Select a measurement view to compare mixed sessions."
                else:
                    compare_readings_all = self._store.readings.list_for_session(selected_compare_session_id)
                    compare_groups = _build_session_replay_groups(compare_readings_all)
                    compare_group = next(
                        (group for group in compare_groups if group.context_id == selected_group.context_id),
                        None,
                    )
                    if compare_group is None:
                        compare_summary_text = f"{compare_session_label} does not contain {selected_group.label}."
                    else:
                        compare_readings = _coerce_group_display_unit(
                            compare_group,
                            unit_text or selected_group.display_unit,
                        )
                        compare_points = tuple(_chart_points(compare_readings, axis_mode=chart_axis_mode))
                        compare_stats = summarize_readings(compare_readings)
                        compare_summary_text = _comparison_summary_text(
                            compare_session_label,
                            primary_stats,
                            compare_stats,
                            unit_text or selected_group.display_unit,
                        )

        marker_points = tuple(_marker_points(filtered_readings, filtered_markers, axis_mode=chart_axis_mode))
        marker_rows = tuple(_marker_vm(marker) for marker in filtered_markers)
        contexts = tuple(
            SessionContextViewModel(
                context_id=group.context_id,
                label=group.label,
                display_text=group.display_text,
            )
            for group in replay_groups
        )
        segment_rows = tuple(
            SessionSegmentViewModel(
                segment_id=segment.segment_id,
                label=segment.label,
                display_text=f"{segment.label} | {segment.start_utc.astimezone(timezone.utc).strftime('%H:%M:%S UTC')} | {len(segment.readings)} readings",
            )
            for segment in matching_segments
        )
        chart_x_mode, chart_x_title = _chart_axis_details(chart_axis_mode)
        with self._lock:
            self._session = replace(
                self._session,
                selected_session_id=session_id,
                selected_context_id=selected_context_id,
                selected_context_label=context_label,
                selected_replay_channel=(
                    selected_replay_channel if selected_group is None else selected_group.readings[0].metadata.get("channel_role", selected_replay_channel)
                ),
                available_replay_channels=available_replay_channels,
                selected_axis_mode=selected_axis_mode,
                selected_segment_id=selected_segment_id,
                compare_session_id=selected_compare_session_id,
                compare_session_label=compare_session_label,
                active_title_text=session.title or session.session_id,
                reading_count_text=reading_count_text,
                available_contexts=contexts if len(contexts) > 1 else (),
                available_segments=segment_rows if selected_axis_mode == "by_segment" and len(segment_rows) > 1 else segment_rows if selected_axis_mode == "by_segment" else (),
                available_compare_sessions=compare_options,
                selected_summary_text=selected_summary_text,
                compare_summary_text=compare_summary_text,
                selected_unit_text=unit_text,
                selected_session_notes=session.notes or "",
                chart_x_mode=chart_x_mode,
                chart_x_title=chart_x_title,
                selected_markers=marker_rows,
                chart_points=points,
                compare_chart_points=compare_points,
                marker_points=marker_points,
            )

    def select_session_context(self, context_id: str | None) -> None:
        session_id = self.session_view_model().selected_session_id
        if session_id is None:
            return
        selected_channel = self.session_view_model().selected_replay_channel
        if context_id is not None and context_id.startswith("secondary\x1f"):
            selected_channel = "secondary"
        elif context_id is not None and context_id.startswith("primary\x1f"):
            selected_channel = "primary"
        with self._lock:
            self._session = replace(
                self._session,
                selected_context_id=context_id,
                selected_replay_channel=selected_channel,
                selected_segment_id=None,
            )
        self.select_session(session_id)

    def select_compare_session(self, session_id: str | None) -> None:
        selected_session_id = self.session_view_model().selected_session_id
        if selected_session_id is None:
            return
        with self._lock:
            self._session = replace(self._session, compare_session_id=session_id)
        self.select_session(selected_session_id)

    def select_live_chart_mode(self, chart_mode: str) -> None:
        with self._lock:
            if chart_mode != self._live_chart_mode:
                self._live_segment_started_at = datetime.now(timezone.utc)
                self._live = replace(
                    self._live,
                    chart_notice_text=f"Live chart mode changed to {_live_chart_mode_label(chart_mode)}.",
                )
            self._live_chart_mode = chart_mode
            self._live = replace(self._live, selected_chart_mode=chart_mode)
            self._refresh_live_chart_locked()

    def select_live_channel(self, channel_role: str) -> None:
        if channel_role not in {"primary", "secondary"}:
            return
        with self._lock:
            self._live = replace(self._live, selected_live_channel=channel_role)
            latest = self._latest_live_reading_for_channel_locked(channel_role)
            if latest is not None:
                self._apply_live_selected_channel_locked(latest)
                self._live_context_key = _reading_context_key(latest)
            else:
                self._live_context_key = None
            self._refresh_live_chart_locked()

    def select_session_axis_mode(self, axis_mode: str) -> None:
        session_id = self.session_view_model().selected_session_id
        if session_id is None:
            return
        with self._lock:
            self._session = replace(self._session, selected_axis_mode=axis_mode, selected_segment_id=None)
        self.select_session(session_id)

    def select_session_segment(self, segment_id: str | None) -> None:
        session_id = self.session_view_model().selected_session_id
        if session_id is None:
            return
        with self._lock:
            self._session = replace(self._session, selected_segment_id=segment_id)
        self.select_session(session_id)

    def select_session_replay_channel(self, channel_role: str) -> None:
        session_id = self.session_view_model().selected_session_id
        if session_id is None or channel_role not in {"primary", "secondary"}:
            return
        current = self.session_view_model()
        matching = [ctx for ctx in current.available_contexts if ctx.context_id.startswith(f"{channel_role}\x1f")]
        selected_context_id = None if not matching else matching[0].context_id
        with self._lock:
            self._session = replace(
                self._session,
                selected_replay_channel=channel_role,
                selected_context_id=selected_context_id,
                selected_segment_id=None,
            )
        self.select_session(session_id)

    def on_reading(self, reading: Reading) -> None:
        value = "--" if reading.value is None else f"{reading.value:.6g}"
        timestamp = reading.timestamp_utc.astimezone(timezone.utc).strftime("%H:%M:%S UTC")
        context_key = _reading_context_key(reading)
        channel_role = _reading_channel_role(reading)
        banner_text = ""
        self._last_reading_time = datetime.now(timezone.utc)
        alert_marker_message: str | None = None
        auto_commit_capture = False
        refresh_workflow_vm = False
        with self._lock:
            self._live_readings.append(reading)
            selected_live_channel = self._live.selected_live_channel or "primary"
            is_selected_channel = channel_role == selected_live_channel or "live_primary_secondary" not in set(
                self._live.available_capabilities
            )
            if is_selected_channel:
                if self._live_context_key is not None and context_key != self._live_context_key:
                    self._live_segment_started_at = reading.timestamp_utc
                    banner_text = f"Live chart reset: meter mode changed to {_reading_context_label(reading)}."
                elif self._live_context_key is None:
                    self._live_segment_started_at = reading.timestamp_utc
                self._live_context_key = context_key
            elif self._live_context_key is None:
                latest_selected = self._latest_live_reading_for_channel_locked(selected_live_channel)
                if latest_selected is not None:
                    self._live_context_key = _reading_context_key(latest_selected)
            active_session = self._recorder.active_session()
            is_logging = active_session is not None
            session_title = None if active_session is None else (active_session.title or active_session.session_id)
            live_kwargs: dict[str, object] = {
                "connection_health": "streaming",
                "session_title": session_title,
                "chart_notice_text": banner_text or self._live.chart_notice_text,
                "is_logging": is_logging,
                "last_updated_text": timestamp,
                "marker_count_text": f"{self._recorder.marker_count()} markers",
                "family_mode_badges": tuple(str(item) for item in reading.metadata.get("family_mode_badges", ()) if item),
            }
            if channel_role == "primary":
                live_kwargs.update(
                    {
                        "live_primary_reading": value,
                        "live_primary_unit_text": reading.unit,
                        "live_primary_label": _reading_context_label(reading),
                    }
                )
            elif channel_role == "secondary":
                live_kwargs.update(
                    {
                        "live_secondary_reading": value,
                        "live_secondary_unit_text": reading.unit,
                        "live_secondary_label": _reading_context_label(reading),
                    }
                )
            self._live = replace(
                self._live,
                **live_kwargs,
            )
            if is_selected_channel:
                self._apply_live_selected_channel_locked(reading)
            self._refresh_live_chart_locked()
            active_workflow = self._workflow_runner.active_state()
            if active_workflow is not None and active_workflow.current_step is not None:
                step = active_workflow.current_step
                if step.requires_reading:
                    auto_commit_capture = self._track_workflow_capture_locked(step, reading)
                else:
                    self._workflow = replace(self._workflow, latest_capture_text=f"Latest live reading: {reading.display_text}")
                refresh_workflow_vm = True
            # Alert threshold check
            alert_active = False
            alert_message = ""
            alert_signature: str | None = None
            alert_event_id = self._live.alert_event_id
            if reading.value is not None:
                if self._alert_high is not None and reading.value > self._alert_high:
                    alert_active = True
                    alert_message = f"HIGH ALERT: {reading.value:.4g} {reading.unit} exceeds {self._alert_high:.4g}"
                    alert_signature = f"high:{self._alert_high}"
                elif self._alert_low is not None and reading.value < self._alert_low:
                    alert_active = True
                    alert_message = f"LOW ALERT: {reading.value:.4g} {reading.unit} below {self._alert_low:.4g}"
                    alert_signature = f"low:{self._alert_low}"
            if alert_active and alert_signature != self._active_alert_signature:
                self._alert_event_id += 1
                alert_event_id = self._alert_event_id
                alert_marker_message = alert_message
            elif not alert_active:
                self._active_alert_signature = None
            if alert_active:
                self._active_alert_signature = alert_signature
            self._live = replace(
                self._live,
                alert_active=alert_active,
                alert_message=alert_message,
                alert_event_id=alert_event_id,
            )
            self._home = replace(self._home, connection_health="streaming", is_busy=False)
            self._discovery = replace(self._discovery, is_connecting=False, is_reconnecting=False)
            self._session = replace(
                self._session,
                reading_count_text=f"{self._recorder.reading_count()} readings",
            )
        if alert_marker_message is not None:
            self._record_system_marker(alert_marker_message, label="alert")
        if auto_commit_capture:
            try:
                self.complete_workflow_step()
            except Exception as exc:
                self.report_error(str(exc))
        elif refresh_workflow_vm:
            self.refresh_workflows()

    def on_notification(self, characteristic_uuid: str, payload: bytes) -> None:
        observed_at = datetime.now(timezone.utc)
        with self._lock:
            self._raw_notifications.append(
                {
                    "characteristic_uuid": characteristic_uuid,
                    "observed_at": observed_at.isoformat(),
                    "payload_hex": bytes(payload).hex(),
                }
            )
            self._settings = replace(
                self._settings,
                live_buffer_text=(
                    f"{len(self._raw_notifications)} raw frame(s) buffered"
                    + (
                        f"; latest {characteristic_uuid.lower()} len={len(payload)}"
                        if characteristic_uuid
                        else ""
                    )
                ),
            )

    def set_alert_thresholds(self, low: float | None, high: float | None) -> None:
        """Set (or clear) value-based alert thresholds."""
        if low is not None and high is not None and low >= high:
            self.set_alert_configuration_error("low threshold must be less than high threshold.")
            return
        self._alert_high = high
        self._alert_low = low
        self._active_alert_signature = None
        with self._lock:
            self._live = replace(
                self._live,
                alert_active=False,
                alert_message="",
                alert_status_text=_alert_status_text(low, high),
            )

    def set_alert_configuration_error(self, message: str) -> None:
        with self._lock:
            self._live = replace(
                self._live,
                alert_status_text=f"Alert config error: {message}",
            )

    def check_reading_freshness(self) -> None:
        """Update the stale-data warning if no reading has arrived recently."""
        with self._lock:
            if not self._live.is_connected or self._live.connection_health != "streaming":
                return
            if self._last_reading_time is None:
                return
            elapsed = (datetime.now(timezone.utc) - self._last_reading_time).total_seconds()
            if elapsed > 5.0:
                stale_text = f"No reading received for {int(elapsed)}s. Device may be unresponsive."
                self._live = replace(
                    self._live,
                    chart_notice_text=stale_text,
                    connection_health="stale",
                )
                self._home = replace(self._home, connection_health="stale")

    def _remember_running_loop(self) -> None:
        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            return

    def _cancel_auto_reconnect(self) -> None:
        task = self._auto_reconnect_task
        self._auto_reconnect_task = None
        if task is not None and not task.done():
            task.cancel()

    def _schedule_auto_reconnect(self, device: DeviceInfo) -> None:
        if self._auto_reconnect_task is not None and not self._auto_reconnect_task.done():
            return
        self._auto_reconnect_task = asyncio.create_task(self._attempt_auto_reconnect(device))

    async def _attempt_auto_reconnect(self, device: DeviceInfo) -> None:
        label = _device_label(device)
        self._record_system_marker("Connection lost. Automatic reconnect started.", label="system")
        last_error: Exception | None = None
        try:
            for attempt in range(1, self._auto_reconnect_attempts + 1):
                if attempt > 1 and self._auto_reconnect_delay_s > 0:
                    await asyncio.sleep(self._auto_reconnect_delay_s)
                self._set_reconnecting_state(device, attempt, self._auto_reconnect_attempts)
                try:
                    reconnected = await asyncio.wait_for(
                        self._device_manager.reconnect(),
                        timeout=self._device_operation_timeout_s,
                    )
                    self._store.upsert_device(reconnected)
                    self.refresh_recent_devices()
                    await asyncio.wait_for(
                        self._device_manager.start_stream(),
                        timeout=self._device_operation_timeout_s,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = exc
                    try:
                        await self._device_manager.disconnect()
                    except Exception:
                        pass
                    continue

                self._set_reconnected_state(reconnected)
                self._record_system_marker("Connection restored after automatic reconnect.", label="system")
                self.refresh_recent_sessions()
                return

            detail = "Automatic reconnect failed. Check that the meter is powered on, nearby, and not held by another app."
            if last_error is not None:
                detail = f"{detail} Last error: {last_error}"
            self._finalize_unexpected_disconnect(diagnostics_text=detail, reconnect_failed=True)
        except asyncio.CancelledError:
            return
        finally:
            if self._auto_reconnect_task is asyncio.current_task():
                self._auto_reconnect_task = None

    def _set_reconnecting_state(self, device: DeviceInfo, attempt: int, total_attempts: int) -> None:
        label = _device_label(device)
        status = f"Reconnecting to {label} ({attempt}/{total_attempts})..."
        with self._lock:
            self._home = replace(
                self._home,
                connection_text=status,
                active_device_text=f"{label} ({device.device_id})",
                message_text="Connection lost. Trying to restore the BLE session...",
                is_busy=True,
                is_connected=False,
                connection_health="reconnecting",
            )
            self._live = replace(
                self._live,
                connection_text=status,
                status_text="Reconnecting",
                is_connected=False,
                connection_health="reconnecting",
                alert_active=False,
                alert_message="",
                chart_notice_text="Connection lost. Attempting automatic reconnect...",
            )
            self._discovery = replace(
                self._discovery,
                selected_device_id=device.device_id,
                status_text=status,
                is_connecting=False,
                is_reconnecting=True,
            )
            self._settings = replace(
                self._settings,
                diagnostics_text=(
                    f"BLE connection dropped for {label}. "
                    f"Attempting automatic reconnect ({attempt}/{total_attempts})."
                ),
            )

    def _set_reconnected_state(self, device: DeviceInfo) -> None:
        label = _device_label(device)
        with self._lock:
            self._current_device = device
            self._home = replace(
                self._home,
                connection_text=f"Connected to {label}",
                active_device_text=f"{label} ({device.device_id})",
                message_text=f"Reconnected to {label}.",
                is_busy=False,
                is_connected=True,
                connection_health="streaming",
            )
            self._live = replace(
                self._live,
                connection_text=f"Connected to {label}",
                status_text="Streaming",
                is_connected=True,
                connection_health="streaming",
                alert_active=False,
                alert_message="",
                chart_notice_text="Connection restored after automatic reconnect.",
            )
            self._discovery = replace(
                self._discovery,
                selected_device_id=device.device_id,
                status_text=f"Reconnected to {label}",
                is_connecting=False,
                is_reconnecting=False,
            )
            self._settings = replace(
                self._settings,
                diagnostics_text=f"Reconnected to {label}; BLE stream resumed.",
            )

    def _finalize_unexpected_disconnect(self, *, diagnostics_text: str, reconnect_failed: bool = False) -> None:
        if self._workflow_runner.active_state() is not None:
            self._workflow_runner.cancel()
            self._workflow_owned_session_id = None
            if reconnect_failed:
                self._workflow_status_message = "Workflow cancelled because automatic reconnect failed."
            else:
                self._workflow_status_message = "Workflow cancelled — device disconnected unexpectedly."
        if self._recorder.active_session() is not None:
            self._record_system_marker(
                "Automatic reconnect failed. Logging stopped." if reconnect_failed else "Device disconnected unexpectedly.",
                label="system",
            )
            self.stop_logging()
        self._set_disconnected_state(
            connection_text="Reconnect failed" if reconnect_failed else "Device disconnected unexpectedly",
            live_status_text="Reconnect failed" if reconnect_failed else "Disconnected",
            discovery_status_text="Reconnect failed" if reconnect_failed else "Device lost",
            diagnostics_text=diagnostics_text,
            connection_health="error" if reconnect_failed else "disconnected",
        )
        self.refresh_workflows()

    def _record_system_marker(self, note: str, *, label: str) -> None:
        if self._recorder.active_session() is None:
            return
        try:
            self.add_marker(note, label=label)
        except Exception:
            pass

    def _resolve_export_session_id(self, session_id: str | None) -> str:
        target = session_id or self._last_completed_session_id
        if not target:
            active = self._recorder.active_session()
            target = None if active is None else active.session_id
        if not target:
            raise RuntimeError("No session available to export.")
        return target

    def _resolve_export_workflow_run_id(self, run_id: str | None) -> str:
        target = run_id or self.workflow_view_model().selected_run_id
        if not target:
            active_state = self._workflow_runner.active_state()
            target = None if active_state is None else active_state.run.run_id
        if not target:
            raise RuntimeError("No workflow run available to export.")
        return target

    def _resolve_export_path(self, path: str | Path, default_name: str) -> Path:
        candidate = Path(path)
        if candidate.name != "." and str(candidate) not in {"", "."}:
            return candidate
        return self._export_directory / default_name

    def _workflow_run_details(
        self,
        run_id: str,
        *,
        active_state: WorkflowRunState | None = None,
    ) -> tuple[WorkflowDefinition, WorkflowRun, tuple[WorkflowStepResult, ...], Session | None] | None:
        if active_state is not None and active_state.run.run_id == run_id:
            run = active_state.run
            definition = active_state.definition
            results = active_state.completed_steps
        else:
            run = self._store.workflow_runs.get(run_id)
            if run is None:
                return None
            definition = self._workflow_catalog.get(run.workflow_id)
            if definition is None:
                return None
            results = tuple(self._workflow_runner.results_for_run(run_id))
        session = self._store.sessions.get(run.session_id)
        return definition, run, results, session

    def _set_connection_status(self, status: str) -> None:
        with self._lock:
            self._home = replace(self._home, connection_text=status)
            self._live = replace(self._live, connection_text=status)

    def _set_connecting_state(self, target_label: str) -> None:
        status = f"Connecting to {target_label}..."
        with self._lock:
            self._home = replace(
                self._home,
                connection_text=status,
                message_text="",
                is_connected=False,
                connection_health="connecting",
            )
            self._live = replace(
                self._live,
                connection_text=status,
                status_text="Connecting",
                is_connected=False,
                connection_health="connecting",
                alert_active=False,
                alert_message="",
            )
            self._discovery = replace(self._discovery, status_text=status, is_reconnecting=False)
            self._settings = replace(self._settings, diagnostics_text=status)

    def _set_connected_pending_stream_state(self, device: DeviceInfo) -> None:
        label = device.nickname or device.model_name or device.device_id
        with self._lock:
            self._current_device = device
            self._reset_live_chart_state()
            self._home = replace(
                self._home,
                connection_text=f"Connected to {label}",
                active_device_text=f"{label} ({device.device_id})",
                message_text=f"Connected to {label}. Starting live stream...",
                is_connected=True,
                connection_health="connected",
            )
            self._live = replace(
                self._live,
                connection_text=f"Connected to {label}",
                status_text="Starting stream...",
                is_connected=True,
                available_capabilities=tuple(device.capabilities),
                capability_summary_text=_capability_summary_text(device.capabilities),
                connection_health="connected",
                alert_active=False,
                alert_message="",
                live_primary_reading="--",
                live_primary_unit_text="",
                live_primary_label="Primary",
                live_secondary_reading="--",
                live_secondary_unit_text="",
                live_secondary_label="Secondary",
                family_mode_badges=(),
                selected_live_channel="primary",
                chart_points=(),
                marker_points=(),
                chart_notice_text="",
                summary_text="Min - | Max - | Avg -",
                marker_count_text="0 markers",
                logging_status_text=(
                    "Logging settings not read yet."
                    if "device_logging_config" in set(device.capabilities)
                    else "Logging settings unavailable."
                ),
                logging_interval_seconds_text="",
                logging_duration_seconds_text="",
                logging_manual_stop=False,
            )
            self._session = replace(
                self._session,
                device_memory_status_text=(
                    "Device memory status not read yet."
                    if "device_memory_download" in set(device.capabilities)
                    else "Device memory unavailable."
                ),
                device_memory_capacity_text="",
                device_memory_summary_text="No device-memory preview loaded.",
                device_memory_value_source="average",
                device_memory_sessions=(),
            )
            self._device_memory_cache = None
            self._discovery = replace(
                self._discovery,
                selected_device_id=device.device_id,
                status_text=f"Connected to {label}. Starting live stream...",
                is_connecting=False,
                is_reconnecting=False,
            )
            self._settings = replace(
                self._settings,
                diagnostics_text=f"Connected to {label}. Starting BLE notifications...",
                active_device_text=f"{label} ({device.device_id})",
                active_family_text=_device_family_summary(device),
                active_profile_text=f"Profile: {device.profile_id or '-'}",
                active_capabilities_text=_capability_summary_text(device.capabilities),
                active_services_text=_service_summary_text(self._device_manager.active_runtime_services()),
                live_buffer_text="0 raw frame(s) buffered",
                fixture_status_text="",
            )
            self._raw_notifications.clear()

    def _set_disconnected_state(
        self,
        *,
        connection_text: str,
        live_status_text: str,
        discovery_status_text: str,
        diagnostics_text: str,
        connection_health: str = "disconnected",
    ) -> None:
        with self._lock:
            self._current_device = None
            self._reset_live_chart_state()
            self._home = replace(
                self._home,
                connection_text=connection_text,
                active_device_text="No device connected",
                is_connected=False,
                connection_health=connection_health,
                is_busy=False,
            )
            self._live = replace(
                self._live,
                main_value="--",
                unit_text="",
                measurement_label="Idle",
                available_capabilities=(),
                capability_summary_text="",
                live_primary_reading="--",
                live_primary_unit_text="",
                live_primary_label="Primary",
                live_secondary_reading="--",
                live_secondary_unit_text="",
                live_secondary_label="Secondary",
                family_mode_badges=(),
                selected_live_channel="primary",
                connection_text=connection_text,
                status_text=live_status_text,
                is_connected=False,
                connection_health=connection_health,
                is_logging=False,
                session_title=None,
                last_updated_text="-",
                alert_active=False,
                alert_message="",
                chart_points=(),
                marker_points=(),
                chart_notice_text="",
                summary_text="Min - | Max - | Avg -",
                marker_count_text="0 markers",
                logging_interval_seconds_text="",
                logging_duration_seconds_text="",
                logging_manual_stop=False,
                logging_status_text="Logging settings unavailable.",
            )
            self._session = replace(
                self._session,
                device_memory_status_text="Device memory unavailable.",
                device_memory_capacity_text="",
                device_memory_summary_text="",
                device_memory_value_source="average",
                device_memory_sessions=(),
            )
            self._device_memory_cache = None
            self._discovery = replace(
                self._discovery,
                status_text=discovery_status_text,
                is_connecting=False,
                is_reconnecting=False,
            )
            self._settings = replace(self._settings, diagnostics_text=diagnostics_text)
            self._settings = replace(
                self._settings,
                active_device_text="No device connected",
                active_family_text="",
                active_profile_text="",
                active_capabilities_text="",
                active_services_text="",
                live_buffer_text="",
                fixture_status_text="",
            )
            self._raw_notifications.clear()

    def _set_discovery(
        self,
        *,
        status_text: str,
        devices: tuple[ScannedDeviceViewModel, ...] | None = None,
        selected_device_id: object = _UNCHANGED,
    ) -> None:
        with self._lock:
            self._discovery = replace(
                self._discovery,
                status_text=status_text,
                devices=self._discovery.devices if devices is None else devices,
                selected_device_id=(
                    self._discovery.selected_device_id
                    if selected_device_id is _UNCHANGED
                    else selected_device_id
                ),
            )

    def _report_message(self, message: str) -> None:
        with self._lock:
            self._home = replace(self._home, message_text=message)

    def _set_home_busy(self, is_busy: bool) -> None:
        with self._lock:
            self._home = replace(self._home, is_busy=is_busy)

    def _set_discovery_busy(
        self,
        *,
        is_scanning: bool | object = _UNCHANGED,
        is_connecting: bool | object = _UNCHANGED,
        is_reconnecting: bool | object = _UNCHANGED,
    ) -> None:
        with self._lock:
            self._discovery = replace(
                self._discovery,
                is_scanning=self._discovery.is_scanning if is_scanning is _UNCHANGED else is_scanning,
                is_connecting=self._discovery.is_connecting if is_connecting is _UNCHANGED else is_connecting,
                is_reconnecting=(
                    self._discovery.is_reconnecting
                    if is_reconnecting is _UNCHANGED
                    else is_reconnecting
                ),
            )

    def _device_has_capability(self, capability: str) -> bool:
        device = self._current_device
        if device is None:
            return False
        return capability in set(device.capabilities)

    def _apply_logging_config_to_live(self, config: dict[str, object]) -> None:
        interval_seconds = int(config.get("interval_seconds", 0) or 0)
        duration_seconds = int(config.get("duration_seconds", 0) or 0)
        manual_stop = duration_seconds == 0
        with self._lock:
            self._live = replace(
                self._live,
                logging_interval_seconds_text=str(interval_seconds),
                logging_duration_seconds_text="" if manual_stop else str(duration_seconds),
                logging_manual_stop=manual_stop,
                logging_status_text=(
                    f"Logging settings loaded: interval {interval_seconds}s, "
                    f"duration {'manual' if manual_stop else f'{duration_seconds}s'}."
                ),
            )

    def _apply_device_memory_status_to_session(
        self,
        report: dict[str, object],
        *,
        preview_summary: str | None = None,
        previews: tuple[DeviceMemorySessionViewModel, ...] | None = None,
        value_source: str | None = None,
    ) -> None:
        bytes_logged = int(report.get("bytes_logged") or 0)
        blocks_logged = int(report.get("blocks_logged") or 0)
        state_label = str(report.get("state_label") or "unknown").replace("_", " ")
        capacity_bytes = report.get("capacity_bytes")
        capacity_text = ""
        if isinstance(capacity_bytes, int) and capacity_bytes > 0:
            percent_full = report.get("percent_full")
            percent_text = "" if not isinstance(percent_full, (int, float)) else f" ({percent_full:.2f}% full)"
            capacity_text = f"Capacity {capacity_bytes} byte(s){percent_text}"
        elif report.get("capacity_error"):
            capacity_text = f"Capacity unavailable: {report['capacity_error']}"
        status_text = f"Device memory: {state_label}, {bytes_logged} byte(s), {blocks_logged} block(s)."
        with self._lock:
            self._session = replace(
                self._session,
                device_memory_status_text=status_text,
                device_memory_capacity_text=capacity_text,
                device_memory_summary_text=(
                    self._session.device_memory_summary_text if preview_summary is None else preview_summary
                ),
                device_memory_sessions=self._session.device_memory_sessions if previews is None else previews,
                device_memory_value_source=(
                    self._session.device_memory_value_source if value_source is None else str(value_source)
                ),
            )

    def _reset_live_chart_state(self, start_at: datetime | None = None) -> None:
        self._live_context_key = None
        self._live_segment_started_at = start_at
        self._live_readings.clear()
        self._live_markers = []
        self._last_reading_time = None
        self._reset_workflow_capture_runtime()

    def _reset_workflow_capture_runtime(self) -> None:
        self._workflow_capture = _WorkflowCaptureRuntime()

    def _latest_live_reading_for_channel_locked(self, channel_role: str) -> Reading | None:
        for reading in reversed(self._live_readings):
            if _reading_channel_role(reading) == channel_role:
                return reading
        return None

    def _apply_live_selected_channel_locked(self, reading: Reading) -> None:
        value = "--" if reading.value is None else f"{reading.value:.6g}"
        self._live = replace(
            self._live,
            main_value=value,
            unit_text=reading.unit,
            measurement_label=_reading_context_label(reading),
            status_text=reading.status.value.replace("_", " ").title(),
        )

    def _refresh_live_chart_locked(self) -> None:
        active_session = self._recorder.active_session()
        session_start = None if active_session is None else active_session.started_at
        chart_readings = _live_chart_readings(
            list(self._live_readings),
            self._live_context_key,
            self._live_chart_mode,
            self._live_segment_started_at,
            session_start,
        )
        current_context_id = "" if not chart_readings else _replay_descriptor(chart_readings[-1]).context_id
        chart_markers = _markers_for_context(list(self._live_readings), self._live_markers, current_context_id)
        marker_points = _marker_points(chart_readings, chart_markers, axis_mode="elapsed")
        live_stats = summarize_readings(chart_readings)
        chart_x_mode, chart_x_title = _chart_axis_details("elapsed")
        self._live = replace(
            self._live,
            selected_chart_mode=self._live_chart_mode,
            chart_x_mode=chart_x_mode,
            chart_x_title=chart_x_title,
            summary_text=_summary_text(live_stats),
            chart_points=tuple(_chart_points(chart_readings, axis_mode="elapsed")),
            marker_points=tuple(marker_points),
        )

    def _track_workflow_capture_locked(self, step: WorkflowStep, reading: Reading) -> bool:
        capture = self._workflow_capture
        if capture.step_id != step.step_id:
            self._reset_workflow_capture_runtime()
            capture = self._workflow_capture
            capture.step_id = step.step_id

        valid_reading = _valid_contact_reading(reading)
        if not valid_reading:
            capture.samples.clear()
            capture.state = "no_contact"
            capture.hint_text = "Waiting for a valid numeric reading."
            return False
        try:
            self._workflow_runner.validate_reading_for_step(step, reading)
        except RuntimeError as exc:
            capture.samples.clear()
            capture.state = "no_contact"
            capture.hint_text = str(exc)
            return False

        if capture.pending_reading is not None:
            capture.state = "captured"
            capture.hint_text = f"Captured {capture.pending_reading.display_text}. Continue or retake."
            return False

        if step.interaction_mode == WorkflowInteractionMode.COUNTDOWN_CAPTURE:
            if capture.countdown_deadline is None:
                capture.state = "contact_detected"
                capture.hint_text = "Press Capture Now to start the countdown."
                return False
            remaining = max((capture.countdown_deadline - datetime.now(timezone.utc)).total_seconds(), 0.0)
            if remaining > 0:
                capture.state = "settling"
                capture.hint_text = f"Countdown: {remaining:.1f}s"
                return False
            capture.pending_reading = reading
            capture.state = "captured"
            capture.hint_text = f"Captured {reading.display_text}."
            return step.advance_on_capture

        capture.samples.append(reading)
        if len(capture.samples) == 1:
            capture.state = "contact_detected"
            capture.hint_text = "Contact detected. Hold steady."
            return False

        stable, hint_text = _stable_capture_status(list(capture.samples), step.capture_settings)
        capture.state = "stable" if stable else "settling"
        capture.hint_text = hint_text
        if not stable:
            return False
        capture.pending_reading = capture.samples[-1]
        capture.state = "captured"
        capture.hint_text = f"Captured {capture.pending_reading.display_text}."
        return step.advance_on_capture

    def _finish_workflow_if_complete(self, state: WorkflowRunState) -> None:
        if state.run.result != WorkflowRunResult.COMPLETED:
            return
        self._workflow_status_message = f"Completed {state.definition.title}."
        if self._workflow_owned_session_id == state.run.session_id:
            self.stop_logging()
        self._workflow_owned_session_id = None


def _device_vm(device: DeviceInfo) -> ScannedDeviceViewModel:
    label = _device_label(device)
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


def _device_memory_session_vm(preview: dict[str, object]) -> DeviceMemorySessionViewModel:
    interval_seconds = int(preview.get("interval_seconds") or 0)
    detail_count = int(preview.get("detail_count") or 0)
    return DeviceMemorySessionViewModel(
        preview_id=str(preview.get("preview_id") or ""),
        title=str(preview.get("title") or ""),
        started_at_text=str(preview.get("started_at_text") or "-"),
        ended_at_text=str(preview.get("ended_at_text") or "-"),
        measurement_text=str(preview.get("measurement_text") or "Unknown"),
        interval_text=f"{interval_seconds}s",
        detail_count_text=str(detail_count),
        import_status_text=str(preview.get("import_status") or "Ready"),
    )


def _session_compare_vm(session: Session) -> SessionCompareViewModel:
    started = session.started_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    label = session.title or session.session_id
    return SessionCompareViewModel(
        session_id=session.session_id,
        label=label,
        display_text=f"{label} | {started}",
    )


def _recent_device_vm(device: DeviceInfo) -> RecentDeviceViewModel:
    label = _device_label(device)
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


def _capability_summary_text(capabilities: list[str] | tuple[str, ...]) -> str:
    if not capabilities:
        return ""
    labels = {
        "live_scalar": "Scalar Live",
        "live_primary_secondary": "Primary/Secondary Live",
        "device_logging_config": "Device Logging Settings",
        "device_memory_download": "Device Memory Download",
        "device_memory_clear": "Device Memory Clear",
        "session_import": "Session Import",
        "fieldsense_view": "FieldSense",
        "phase_rotation_view": "Phase Rotation",
        "phase_to_phase_view": "Phase-to-Phase",
        "relative_mode_view": "Relative Mode",
        "continuity_state_view": "Continuity State",
        "self_check_view": "Self Check",
    }
    return ", ".join(labels.get(capability, capability.replace("_", " ").title()) for capability in capabilities)


def _device_family_summary(device: DeviceInfo) -> str:
    family = device.family_id or "-"
    variant = device.variant_id or "-"
    return f"Family: {family} | Variant: {variant} | Support: {device.support_level or '-'}"


def _service_summary_text(services) -> str:
    payload = _json_safe(services)
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    for key, value in payload.items():
        if not value:
            continue
        if isinstance(value, dict):
            parts.append(f"{key}={','.join(sorted(str(item) for item in value.values() if item))}")
        else:
            parts.append(f"{key}={value}")
    return " | ".join(parts)


def _json_safe(value):
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json_safe(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _logging_status_summary_from_download_report(report: object) -> dict[str, object]:
    if not isinstance(report, dict):
        return {}
    status = report.get("status_before")
    normalized = dict(status) if isinstance(status, dict) else {}
    for key in ("capacity_bytes", "capacity_error", "percent_full"):
        if key in report:
            normalized[key] = report[key]
    return normalized


def _device_label(device: DeviceInfo) -> str:
    return device.nickname or device.model_name or device.device_id


def _marker_vm(marker: SessionMarker) -> SessionMarkerViewModel:
    timestamp_text = marker.timestamp_utc.astimezone(timezone.utc).strftime("%H:%M:%S UTC")
    return SessionMarkerViewModel(
        marker_id=marker.marker_id,
        timestamp_text=timestamp_text,
        label=marker.label,
        note=marker.note,
    )


def _summary_text(stats) -> str:
    min_text = "-" if stats.min_value is None else f"{stats.min_value:.6g}"
    max_text = "-" if stats.max_value is None else f"{stats.max_value:.6g}"
    avg_text = "-" if stats.avg_value is None else f"{stats.avg_value:.6g}"
    return (
        f"Min {min_text} | Max {max_text} | Avg {avg_text} | "
        f"Samples {stats.reading_count} | Duration {stats.duration_s:.1f}s"
    )


def _comparison_summary_text(compare_label: str, primary_stats, compare_stats, unit_text: str) -> str:
    avg_delta = _format_delta(primary_stats.avg_value, compare_stats.avg_value, suffix=f" {unit_text}".rstrip())
    max_delta = _format_delta(primary_stats.max_value, compare_stats.max_value, suffix=f" {unit_text}".rstrip())
    duration_delta = _format_delta(primary_stats.duration_s, compare_stats.duration_s, suffix="s")
    sample_delta = primary_stats.reading_count - compare_stats.reading_count
    sample_prefix = "+" if sample_delta > 0 else ""
    return (
        f"Compared with {compare_label}: "
        f"Avg {avg_delta} | Max {max_delta} | Duration {duration_delta} | Samples {sample_prefix}{sample_delta}"
    )


def _format_delta(current_value: float | None, baseline_value: float | None, *, suffix: str = "") -> str:
    if current_value is None or baseline_value is None:
        return "-"
    delta = current_value - baseline_value
    prefix = "+" if delta > 0 else ""
    return f"{prefix}{delta:.4g}{suffix}"


def _alert_status_text(low: float | None, high: float | None) -> str:
    if low is None and high is None:
        return "Alerts disabled."
    parts: list[str] = []
    if low is not None:
        parts.append(f"low < {low:.4g}")
    if high is not None:
        parts.append(f"high > {high:.4g}")
    return f"Alerts armed: {', '.join(parts)}."


def _reading_channel_role(reading: Reading) -> str:
    role = str(reading.metadata.get("channel_role") or "primary").strip().lower()
    return role if role in {"primary", "secondary"} else "primary"


def _is_multi_channel_reading(reading: Reading) -> bool:
    metadata = reading.metadata
    return any(f"mode_attr_{index}" in metadata for index in range(1, 6))


def _reading_context_key(reading: Reading) -> tuple[str, str, str, str]:
    return (
        _reading_channel_role(reading),
        reading.measurement_type.value,
        reading.unit or "",
        reading.mode or "",
    )


def _reading_context_id(reading: Reading) -> str:
    return "\x1f".join(_reading_context_key(reading))


def _reading_context_label(reading: Reading) -> str:
    channel_role = _reading_channel_role(reading)
    label = reading.measurement_type.value.replace("_", " ").title()
    if _is_multi_channel_reading(reading):
        label = f"{channel_role.title()} {label}"
    parts = [label]
    if reading.unit:
        parts.append(reading.unit)
    if reading.mode:
        parts.append(reading.mode.upper())
    return " / ".join(parts)


def _build_session_replay_groups(readings: list[Reading]) -> list[_ReplayGroup]:
    grouped: dict[str, tuple[_ReplayDescriptor, list[Reading]]] = {}
    for reading in readings:
        descriptor = _replay_descriptor(reading)
        current = grouped.get(descriptor.context_id)
        if current is None:
            grouped[descriptor.context_id] = (descriptor, [reading])
        else:
            current[1].append(reading)

    has_known_groups = any(not descriptor.is_unknown for descriptor, _ in grouped.values())
    groups: list[_ReplayGroup] = []
    for descriptor, raw_group in grouped.values():
        numeric_count = sum(1 for reading in raw_group if reading.value is not None)
        if numeric_count == 0:
            continue
        if descriptor.is_unknown and has_known_groups and len(raw_group) <= _UNKNOWN_REPLAY_THRESHOLD:
            continue
        normalized_group = _normalize_replay_group(raw_group, descriptor)
        display_unit = next((reading.unit for reading in normalized_group if reading.unit), "")
        groups.append(
            _ReplayGroup(
                context_id=descriptor.context_id,
                label=descriptor.label,
                display_text=f"{descriptor.label} ({len(raw_group)} readings)",
                readings=normalized_group,
                normalization_key=descriptor.normalization_key,
                display_unit=display_unit,
                total_count=len(raw_group),
                numeric_count=numeric_count,
            )
        )

    groups.sort(key=lambda group: (-group.total_count, group.label))
    return groups


def _replay_descriptor(reading: Reading) -> _ReplayDescriptor:
    measurement_type = reading.measurement_type
    unit_family = str(reading.metadata.get("unit_family") or "").strip().lower()
    channel_role = _reading_channel_role(reading)

    def _with_channel(context_id: str, label: str, normalization_key: str | None, *, is_unknown: bool = False) -> _ReplayDescriptor:
        display_label = f"{channel_role.title()} {label}" if _is_multi_channel_reading(reading) else label
        return _ReplayDescriptor(
            context_id=f"{channel_role}\x1f{context_id}",
            label=display_label,
            normalization_key=normalization_key,
            channel_role=channel_role,
            is_unknown=is_unknown,
        )

    if measurement_type == MeasurementType.VOLTAGE_AC:
        return _with_channel("voltage_ac", "Voltage AC", "voltage")
    if measurement_type == MeasurementType.VOLTAGE_DC:
        return _with_channel("voltage_dc", "Voltage DC", "voltage")
    if measurement_type == MeasurementType.VOLTAGE_AC_DC:
        return _with_channel("voltage_acdc", "Voltage AC+DC", "voltage")
    if measurement_type == MeasurementType.CURRENT_AC:
        return _with_channel("current_ac", "Current AC", "current")
    if measurement_type == MeasurementType.CURRENT_DC:
        return _with_channel("current_dc", "Current DC", "current")
    if measurement_type == MeasurementType.CURRENT_AC_DC:
        return _with_channel("current_acdc", "Current AC+DC", "current")
    if measurement_type == MeasurementType.CURRENT_INRUSH:
        return _with_channel("current_inrush", "Current Inrush", "current")
    if measurement_type == MeasurementType.RESISTANCE:
        return _with_channel("resistance", "Resistance", "resistance")
    if measurement_type == MeasurementType.CAPACITANCE:
        return _with_channel("capacitance", "Capacitance", "capacitance")
    if measurement_type == MeasurementType.FREQUENCY:
        return _with_channel("frequency", "Frequency", "frequency")
    if measurement_type == MeasurementType.DUTY_CYCLE:
        return _with_channel("duty_cycle", "Duty Cycle", None)
    if measurement_type == MeasurementType.TEMPERATURE:
        unit_suffix = f" {reading.unit}" if reading.unit else ""
        context_id = f"temperature:{reading.unit or 'unknown'}"
        return _with_channel(context_id, f"Temperature{unit_suffix}", None)
    if measurement_type == MeasurementType.CONTINUITY:
        return _with_channel("continuity", "Continuity", None)
    if measurement_type == MeasurementType.CONDUCTANCE:
        return _with_channel("conductance", "Conductance", None)
    if measurement_type == MeasurementType.PRESSURE:
        return _with_channel(f"pressure:{reading.unit or 'unknown'}", "Pressure", None)
    if measurement_type == MeasurementType.FIELDSENSE:
        return _with_channel("fieldsense", "FieldSense", "voltage")
    if measurement_type == MeasurementType.PHASE_ROTATION:
        return _with_channel("phase_rotation", "Phase Rotation", None)
    if measurement_type == MeasurementType.LOW_PASS_VFD:
        return _with_channel("low_pass_vfd", "Low-Pass VFD", "voltage")

    if unit_family == "voltage":
        if reading.mode == "ac":
            return _with_channel("voltage_ac", "Voltage AC", "voltage")
        if reading.mode == "dc" or reading.unit == "mV":
            return _with_channel("voltage_dc", "Voltage DC", "voltage")
        return _with_channel("voltage", "Voltage", "voltage")
    if unit_family == "current":
        if reading.mode == "ac":
            return _with_channel("current_ac", "Current AC", "current")
        if reading.mode == "dc":
            return _with_channel("current_dc", "Current DC", "current")
        if reading.mode == "acdc":
            return _with_channel("current_acdc", "Current AC+DC", "current")
        return _with_channel("current", "Current", "current")
    if unit_family == "resistance":
        return _with_channel("resistance", "Resistance", "resistance")
    if unit_family == "capacitance":
        return _with_channel("capacitance", "Capacitance", "capacitance")
    if unit_family == "frequency":
        return _with_channel("frequency", "Frequency", "frequency")
    if unit_family == "duty_cycle":
        return _with_channel("duty_cycle", "Duty Cycle", None)
    if unit_family == "temperature":
        unit_suffix = f" {reading.unit}" if reading.unit else ""
        context_id = f"temperature:{reading.unit or 'unknown'}"
        return _with_channel(context_id, f"Temperature{unit_suffix}", None)

    return _with_channel("unknown", "Unknown / Transitional", None, is_unknown=True)


def _normalize_replay_group(readings: list[Reading], descriptor: _ReplayDescriptor) -> list[Reading]:
    if descriptor.normalization_key is None:
        return readings

    unit_scale = dict(_REPLAY_UNIT_SCALES[descriptor.normalization_key])
    base_values = [
        _base_unit_value(reading, descriptor.normalization_key)
        for reading in readings
        if reading.value is not None
    ]
    display_unit = _choose_display_unit(descriptor.normalization_key, base_values)
    display_factor = unit_scale[display_unit]
    normalized: list[Reading] = []
    for reading in readings:
        if reading.value is None:
            normalized.append(replace(reading, unit=display_unit))
            continue
        base_value = _base_unit_value(reading, descriptor.normalization_key)
        if base_value is None:
            normalized.append(replace(reading, unit=display_unit))
            continue
        normalized.append(replace(reading, value=base_value / display_factor, unit=display_unit))
    return normalized


def _coerce_group_display_unit(group: _ReplayGroup, display_unit: str) -> list[Reading]:
    if not display_unit or group.normalization_key is None or group.display_unit == display_unit:
        return group.readings
    return _normalize_readings_to_unit(group.readings, group.normalization_key, display_unit)


def _normalize_readings_to_unit(
    readings: list[Reading],
    normalization_key: str,
    display_unit: str,
) -> list[Reading]:
    unit_scale = dict(_REPLAY_UNIT_SCALES[normalization_key])
    display_factor = unit_scale[display_unit]
    normalized: list[Reading] = []
    for reading in readings:
        if reading.value is None:
            normalized.append(replace(reading, unit=display_unit))
            continue
        base_value = _base_unit_value(reading, normalization_key)
        if base_value is None:
            normalized.append(replace(reading, unit=display_unit))
            continue
        normalized.append(replace(reading, value=base_value / display_factor, unit=display_unit))
    return normalized


def _base_unit_value(reading: Reading, normalization_key: str) -> float | None:
    if reading.value is None:
        return None
    unit_scale = dict(_REPLAY_UNIT_SCALES.get(normalization_key, ()))
    factor = unit_scale.get(reading.unit)
    if factor is None:
        return float(reading.value)
    return float(reading.value) * factor


def _choose_display_unit(normalization_key: str, base_values: list[float | None]) -> str:
    units = _REPLAY_UNIT_SCALES[normalization_key]
    numeric_values = [abs(value) for value in base_values if value is not None]
    if not numeric_values:
        return units[-1][0]
    typical = median(numeric_values)
    if typical == 0:
        return units[-1][0]
    for unit, factor in reversed(units):
        if typical / factor >= 1:
            return unit
    return units[0][0]


def _markers_for_context(readings: list[Reading], markers: list[SessionMarker], context_id: str) -> list[SessionMarker]:
    if not readings or not markers or not context_id:
        return []
    numeric_readings = [reading for reading in readings if reading.value is not None]
    if not numeric_readings:
        return []
    selected: list[SessionMarker] = []
    reading_index = 0
    current_context_id = _replay_descriptor(numeric_readings[reading_index]).context_id
    for marker in markers:
        while (
            reading_index + 1 < len(numeric_readings)
            and numeric_readings[reading_index + 1].timestamp_utc <= marker.timestamp_utc
        ):
            reading_index += 1
            current_context_id = _replay_descriptor(numeric_readings[reading_index]).context_id
        if current_context_id == context_id:
            selected.append(marker)
    return selected


def _derive_mode_segments(readings: list[Reading], *, gap_threshold_s: float = 5.0) -> list[_DerivedSegment]:
    segments: list[_DerivedSegment] = []
    current: list[Reading] = []
    current_descriptor: _ReplayDescriptor | None = None
    for reading in readings:
        if reading.value is None:
            continue
        descriptor = _replay_descriptor(reading)
        if not current:
            current = [reading]
            current_descriptor = descriptor
            continue
        gap_s = max((reading.timestamp_utc - current[-1].timestamp_utc).total_seconds(), 0.0)
        if descriptor.context_id != current_descriptor.context_id or gap_s > gap_threshold_s:
            normalized = _normalize_replay_group(current, current_descriptor)
            segments.append(
                _DerivedSegment(
                    segment_id=f"segment_{len(segments) + 1}",
                    segment_index=len(segments) + 1,
                    context_id=current_descriptor.context_id,
                    label=current_descriptor.label,
                    normalization_key=current_descriptor.normalization_key,
                    measurement_type=normalized[0].measurement_type.value if normalized else "unknown",
                    unit=next((item.unit for item in normalized if item.unit), ""),
                    mode=normalized[0].mode if normalized else "",
                    start_utc=normalized[0].timestamp_utc,
                    end_utc=normalized[-1].timestamp_utc,
                    readings=tuple(normalized),
                )
            )
            current = [reading]
            current_descriptor = descriptor
            continue
        current.append(reading)
    if current and current_descriptor is not None:
        normalized = _normalize_replay_group(current, current_descriptor)
        segments.append(
            _DerivedSegment(
                segment_id=f"segment_{len(segments) + 1}",
                segment_index=len(segments) + 1,
                context_id=current_descriptor.context_id,
                label=current_descriptor.label,
                normalization_key=current_descriptor.normalization_key,
                measurement_type=normalized[0].measurement_type.value if normalized else "unknown",
                unit=next((item.unit for item in normalized if item.unit), ""),
                mode=normalized[0].mode if normalized else "",
                start_utc=normalized[0].timestamp_utc,
                end_utc=normalized[-1].timestamp_utc,
                readings=tuple(normalized),
            )
        )
    return segments


def _chart_points(readings: list[Reading], *, axis_mode: str = "elapsed") -> list[tuple[float, float]]:
    numeric = [reading for reading in readings if reading.value is not None]
    if not numeric:
        return []
    if axis_mode == "utc":
        return [
            (reading.timestamp_utc.timestamp() * 1000.0, float(reading.value))
            for reading in numeric
            if reading.value is not None
        ]
    start = numeric[0].timestamp_utc
    return [(max((reading.timestamp_utc - start).total_seconds(), 0.0), float(reading.value)) for reading in numeric]


def _marker_points(
    readings: list[Reading],
    markers: list[SessionMarker],
    *,
    axis_mode: str = "elapsed",
) -> list[tuple[float, float]]:
    numeric = [reading for reading in readings if reading.value is not None]
    if not numeric:
        return []
    start = numeric[0].timestamp_utc
    marker_values: list[tuple[float, float]] = []
    numeric_index = 0
    current_value = float(numeric[0].value)
    for marker in markers:
        while numeric_index + 1 < len(numeric) and numeric[numeric_index + 1].timestamp_utc <= marker.timestamp_utc:
            numeric_index += 1
            current_value = float(numeric[numeric_index].value)
        x_value = (
            marker.timestamp_utc.timestamp() * 1000.0
            if axis_mode == "utc"
            else max((marker.timestamp_utc - start).total_seconds(), 0.0)
        )
        marker_values.append((x_value, current_value))
    return marker_values


def _chart_axis_details(axis_mode: str) -> tuple[str, str]:
    if axis_mode == "utc":
        return "datetime", "UTC"
    return "elapsed", "Seconds"


def _live_chart_mode_label(chart_mode: str) -> str:
    mapping = {
        "rolling_30s": "Rolling 30s",
        "rolling_60s": "Rolling 60s",
        "rolling_5m": "Rolling 5m",
        "since_mode_start": "Since mode start",
        "since_session_start": "Since session start",
    }
    return mapping.get(chart_mode, chart_mode.replace("_", " "))


def _live_chart_readings(
    readings: list[Reading],
    context_key: tuple[str, str, str] | None,
    chart_mode: str,
    segment_started_at: datetime | None,
    session_started_at: datetime | None,
) -> list[Reading]:
    if context_key is None:
        return []
    filtered = [
        reading
        for reading in readings
        if reading.value is not None and _reading_context_key(reading) == context_key
    ]
    if not filtered:
        return []
    latest_ts = filtered[-1].timestamp_utc
    if chart_mode == "rolling_30s":
        cutoff = latest_ts - timedelta(seconds=30)
        return [reading for reading in filtered if reading.timestamp_utc >= cutoff]
    if chart_mode == "rolling_60s":
        cutoff = latest_ts - timedelta(seconds=60)
        return [reading for reading in filtered if reading.timestamp_utc >= cutoff]
    if chart_mode == "rolling_5m":
        cutoff = latest_ts - timedelta(minutes=5)
        return [reading for reading in filtered if reading.timestamp_utc >= cutoff]
    if chart_mode == "since_mode_start" and segment_started_at is not None:
        return [reading for reading in filtered if reading.timestamp_utc >= segment_started_at]
    if chart_mode == "since_session_start" and session_started_at is not None:
        return [reading for reading in filtered if reading.timestamp_utc >= session_started_at]
    return filtered


def _valid_contact_reading(reading: Reading) -> bool:
    return (
        reading.value is not None
        and reading.status not in {ReadingStatus.INVALID, ReadingStatus.NO_SIGNAL}
    )


def _stable_capture_status(readings: list[Reading], settings: WorkflowCaptureSettings) -> tuple[bool, str]:
    numeric = [reading for reading in readings if reading.value is not None]
    if len(numeric) < settings.min_samples:
        return False, f"Collecting samples ({len(numeric)}/{settings.min_samples})."
    duration_s = max((numeric[-1].timestamp_utc - numeric[0].timestamp_utc).total_seconds(), 0.0)
    if duration_s < settings.stable_for_s:
        return False, f"Settling for {settings.stable_for_s:.2f}s."
    values = [float(reading.value) for reading in numeric]
    reference = max(abs(values[-1]), 1.0)
    tolerance = settings.absolute_tolerance
    if tolerance is None:
        tolerance = reference * settings.relative_tolerance
    if max(values) - min(values) <= tolerance:
        return True, f"Stable for {duration_s:.2f}s."
    return False, "Reading still moving."


def _workflow_definition_vm(definition: WorkflowDefinition) -> WorkflowDefinitionViewModel:
    return WorkflowDefinitionViewModel(
        workflow_id=definition.workflow_id,
        title=definition.title,
        category=definition.category,
        description=definition.description,
        step_count_text=f"{len(definition.steps)} steps",
    )


def _workflow_step_vm(result: WorkflowStepResult, definition: WorkflowDefinition) -> WorkflowStepViewModel:
    step = next((item for item in definition.steps if item.step_id == result.step_id), None)
    title = result.step_id if step is None else step.title
    instruction = "" if step is None else step.instruction
    if result.status == WorkflowStepResultStatus.CAPTURED:
        status_text = "Captured"
    elif result.status == WorkflowStepResultStatus.SKIPPED:
        status_text = "Skipped"
    else:
        status_text = "Completed"
    detail = _workflow_result_detail(result)
    return WorkflowStepViewModel(
        step_id=result.step_id,
        title=title,
        instruction=instruction,
        status_text=status_text,
        detail_text=detail,
    )


def _workflow_run_vm(run: WorkflowRun) -> WorkflowRunSummaryViewModel:
    started = run.started_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return WorkflowRunSummaryViewModel(
        run_id=run.run_id,
        workflow_id=run.workflow_id,
        title=run.workflow_title or run.workflow_id,
        session_id=run.session_id,
        started_at_text=started,
        result_text=run.result.value.replace("_", " ").title(),
    )


def _workflow_run_summary_text(
    run: WorkflowRun,
    *,
    session_title: str | None = None,
    viewing_active: bool = False,
) -> str:
    started = run.started_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    result_text = run.result.value.replace("_", " ").title()
    title = run.workflow_title or run.workflow_id
    session_label = run.session_id if not session_title or session_title == run.session_id else f"{session_title} ({run.session_id})"
    active_suffix = " | Active run" if viewing_active and run.result == WorkflowRunResult.IN_PROGRESS else ""
    return f"Viewing run: {title} | {started} | {result_text} | Session {session_label}{active_suffix}"


def _workflow_definition_report_text(definition: WorkflowDefinition) -> str:
    lines = [
        "Workflow Report",
        "===============",
        f"Title: {definition.title}",
        f"Category: {definition.category}",
    ]
    if definition.description:
        lines.append(f"Description: {definition.description}")
    if definition.estimated_duration_min is not None:
        lines.append(f"Estimated duration: {definition.estimated_duration_min} min")
    if definition.tags:
        lines.append(f"Tags: {', '.join(definition.tags)}")
    lines.extend(
        [
            "",
            "No run selected yet. Start this workflow to generate a report with step outcomes and captured readings.",
            "",
            "Planned Steps",
            "-------------",
        ]
    )
    for index, step in enumerate(definition.steps, start=1):
        lines.append(f"{index}. {step.title}")
        if step.instruction:
            lines.append(f"   Instruction: {step.instruction}")
        lines.append(f"   Mode: {_workflow_interaction_mode_text(step)}")
        lines.append(f"   Requirement: {_workflow_requirement_text(step)}")
        if step.note_prompt:
            lines.append(f"   Note prompt: {step.note_prompt}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _historical_workflow_step_summary(
    definition: WorkflowDefinition,
    run: WorkflowRun,
    results: tuple[WorkflowStepResult, ...] | list[WorkflowStepResult],
) -> tuple[str, str, str]:
    next_index = min(len(results), len(definition.steps))
    next_step = definition.steps[next_index] if next_index < len(definition.steps) else None
    if next_step is None or run.result == WorkflowRunResult.COMPLETED:
        return "Workflow complete", "", ""
    if run.result == WorkflowRunResult.ABORTED:
        return f"Stopped before: {next_step.title}", next_step.instruction, _workflow_requirement_text(next_step)
    return f"Pending step: {next_step.title}", next_step.instruction, _workflow_requirement_text(next_step)


def _workflow_report_text(
    definition: WorkflowDefinition,
    run: WorkflowRun,
    results: tuple[WorkflowStepResult, ...] | list[WorkflowStepResult],
    *,
    session_title: str | None = None,
) -> str:
    result_text = run.result.value.replace("_", " ").title()
    started = run.started_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ended = "-" if run.ended_at is None else run.ended_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    duration_text = "-"
    if run.ended_at is not None:
        duration_text = f"{max((run.ended_at - run.started_at).total_seconds(), 0.0):.1f}s"
    session_label = run.session_id if not session_title or session_title == run.session_id else f"{session_title} ({run.session_id})"

    results_by_step = {result.step_id: result for result in results}
    captured_count = sum(1 for result in results if result.status == WorkflowStepResultStatus.CAPTURED)
    completed_count = sum(1 for result in results if result.status == WorkflowStepResultStatus.COMPLETED)
    skipped_count = sum(1 for result in results if result.status == WorkflowStepResultStatus.SKIPPED)

    lines = [
        "Workflow Report",
        "===============",
        f"Title: {definition.title}",
        f"Run ID: {run.run_id}",
        f"Workflow ID: {run.workflow_id}",
        f"Result: {result_text}",
        f"Session: {session_label}",
        f"Started: {started}",
        f"Ended: {ended}",
        f"Duration: {duration_text}",
        f"Progress: {min(len(results), len(definition.steps))}/{len(definition.steps)} steps",
        f"Summary: {captured_count} captured | {completed_count} completed | {skipped_count} skipped",
        "",
        "Step Results",
        "------------",
    ]

    for index, step in enumerate(definition.steps, start=1):
        lines.append(f"{index}. {step.title}")
        if step.instruction:
            lines.append(f"   Instruction: {step.instruction}")
        lines.append(f"   Mode: {_workflow_interaction_mode_text(step)}")
        lines.append(f"   Requirement: {_workflow_requirement_text(step)}")
        result = results_by_step.get(step.step_id)
        if result is None:
            lines.append("   Status: Pending")
            lines.append("")
            continue
        lines.append(f"   Status: {result.status.value.replace('_', ' ').title()}")
        lines.append(f"   Completed: {result.completed_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        if result.reading is not None:
            lines.append(f"   Reading: {result.reading.display_text}")
        if result.note:
            lines.append(f"   Note: {result.note}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _workflow_requirement_text(step: WorkflowStep) -> str:
    if not step.requires_reading:
        if step.interaction_mode == WorkflowInteractionMode.OBSERVE_AND_CONFIRM:
            return "Observe and confirm manually"
        return "Manual checklist step"
    fragments = ["Capture the current live reading"]
    if step.interaction_mode == WorkflowInteractionMode.STABLE_CAPTURE:
        fragments.append(f"auto-capture once stable for {step.capture_settings.stable_for_s:.2f}s")
    elif step.interaction_mode == WorkflowInteractionMode.COUNTDOWN_CAPTURE:
        fragments.append(f"capture after {step.capture_settings.countdown_s:.1f}s countdown")
    if step.expected_measurement_type is not None:
        fragments.append(f"type {step.expected_measurement_type.value}")
    if step.expected_unit:
        fragments.append(f"unit {step.expected_unit}")
    fragments.append("auto-advance" if step.advance_on_capture else "pause for continue/retake")
    return " | ".join(fragments)


def _workflow_result_detail(result: WorkflowStepResult) -> str:
    fragments = [result.completed_at.astimezone(timezone.utc).strftime("%H:%M:%S UTC")]
    if result.reading is not None:
        fragments.append(result.reading.display_text or result.reading.unit or "captured reading")
    if result.note:
        fragments.append(result.note)
    return " | ".join(fragments)


def _latest_capture_text(results: tuple[WorkflowStepResult, ...] | list[WorkflowStepResult]) -> str:
    for result in reversed(list(results)):
        if result.reading is not None:
            return f"Last capture: {result.reading.display_text}"
    if results:
        last = list(results)[-1]
        return f"Last step: {last.step_id} ({last.status.value})"
    return "No captured step yet"


def _capture_state_text(state: str) -> str:
    mapping = {
        "idle": "",
        "no_contact": "No contact",
        "contact_detected": "Contact detected",
        "settling": "Settling",
        "stable": "Stable",
        "captured": "Captured",
    }
    return mapping.get(state, state.replace("_", " ").title())


def _workflow_interaction_mode_text(step: WorkflowStep) -> str:
    mapping = {
        WorkflowInteractionMode.MANUAL_CHECK: "Manual Check",
        WorkflowInteractionMode.STABLE_CAPTURE: "Stable Capture",
        WorkflowInteractionMode.COUNTDOWN_CAPTURE: "Countdown Capture",
        WorkflowInteractionMode.OBSERVE_AND_CONFIRM: "Observe And Confirm",
    }
    return mapping.get(step.interaction_mode, step.interaction_mode.value.replace("_", " ").title())


def _workflow_definition_payload(definition: WorkflowDefinition) -> dict[str, object]:
    payload: dict[str, object] = {
        "workflow_id": definition.workflow_id,
        "title": definition.title,
        "description": definition.description,
        "category": definition.category,
        "tags": list(definition.tags),
        "steps": [],
    }
    if definition.estimated_duration_min is not None:
        payload["estimated_duration_min"] = definition.estimated_duration_min

    step_payloads: list[dict[str, object]] = []
    for step in definition.steps:
        row: dict[str, object] = {
            "id": step.step_id,
            "title": step.title,
            "instruction": step.instruction,
            "capture": step.capture,
            "interaction_mode": step.interaction_mode.value,
            "advance_on_capture": step.advance_on_capture,
        }
        if step.expected_measurement_type is not None:
            row["expected_measurement_type"] = _measurement_type_value(step.expected_measurement_type)
        if step.expected_unit:
            row["expected_unit"] = step.expected_unit
        if step.note_prompt:
            row["note_prompt"] = step.note_prompt
        if step.requires_reading:
            row["capture_settings"] = {
                "stable_for_s": step.capture_settings.stable_for_s,
                "min_samples": step.capture_settings.min_samples,
                "relative_tolerance": step.capture_settings.relative_tolerance,
                "absolute_tolerance": step.capture_settings.absolute_tolerance,
                "countdown_s": step.capture_settings.countdown_s,
            }
        if step.metadata:
            row["metadata"] = dict(step.metadata)
        step_payloads.append(row)
    payload["steps"] = step_payloads
    return payload


def _measurement_type_value(value: MeasurementType | str) -> str:
    if isinstance(value, MeasurementType):
        return value.value
    return str(value)
