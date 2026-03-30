from __future__ import annotations

import asyncio
from collections import deque
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
    SessionMarkerViewModel,
    SessionContextViewModel,
    SettingsViewModel,
    SessionSummaryViewModel,
    SessionViewModel,
    WorkflowDefinitionViewModel,
    WorkflowRunSummaryViewModel,
    WorkflowStepViewModel,
    WorkflowViewModel,
)
from fluke_app import ExportService, SessionRecorder, WorkflowRunner, load_workflow_catalog, new_session
from fluke_app.export_service import SessionCsvExporter, SessionJsonExporter
from fluke_core.enums import WorkflowRunResult, WorkflowStepResultStatus
from fluke_core.models.marker import SessionMarker
from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_core.models.session import Session
from fluke_core.models.workflow import WorkflowDefinition, WorkflowRun, WorkflowRunState, WorkflowStep, WorkflowStepResult
from fluke_core.services.statistics import summarize_readings

_UNCHANGED = object()


class AppPresenter:
    def __init__(
        self,
        device_manager: object,
        store: object,
        app_version: str = "0.1.0",
        export_directory: str | Path = "exports",
        device_operation_timeout_s: float = 10.0,
        workflow_catalog: object | None = None,
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
        self._workflow_catalog = workflow_catalog or load_workflow_catalog()
        self._workflow_runner = WorkflowRunner(
            self._workflow_catalog,
            store.workflow_runs,
            store.workflow_step_results,
        )
        self._workflow = WorkflowViewModel()
        self._workflow_status_message = "Select a workflow to review the steps."
        self._workflow_owned_session_id: str | None = None
        self._current_device: DeviceInfo | None = None
        self._last_completed_session_id: str | None = None
        self._live_points: deque[tuple[float, float]] = deque(maxlen=300)
        self._live_marker_points: deque[tuple[float, float]] = deque(maxlen=100)
        self._live_readings: list[Reading] = []
        self._live_context_key: tuple[str, str, str] | None = None
        self._chart_t0: datetime | None = None
        self._device_manager.subscribe_readings(self._recorder.on_reading)
        self._device_manager.subscribe_readings(self.on_reading)
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
        target_device_id = device_id or self._discovery.selected_device_id
        if not target_device_id:
            raise RuntimeError("Select a device before connecting.")

        self._set_home_busy(True)
        self._set_discovery_busy(is_connecting=True)
        try:
            self._set_connecting_state(target_device_id)
            try:
                device = await asyncio.wait_for(
                    self._device_manager.connect(target_device_id, profile_id=profile_id),
                    timeout=self._device_operation_timeout_s,
                )
            except asyncio.TimeoutError as exc:
                self._set_discovery(status_text=f"Connection timed out for {target_device_id}")
                self._set_connection_status("Connection timed out")
                raise RuntimeError(f"Timed out while connecting to {target_device_id}.") from exc

            label = device.nickname or device.model_name or device.device_id
            try:
                self._store.upsert_device(device)
                self._set_connected_pending_stream_state(device)
                self.refresh_recent_devices()
                await asyncio.wait_for(
                    self._device_manager.start_stream(),
                    timeout=self._device_operation_timeout_s,
                )
            except asyncio.TimeoutError as exc:
                await self._device_manager.disconnect()
                self._set_disconnected_state(
                    connection_text="Disconnected",
                    live_status_text="Disconnected",
                    discovery_status_text=f"Connected to {label}, but live stream startup timed out.",
                    diagnostics_text=f"Live stream startup timed out for {label}.",
                )
                raise RuntimeError(f"Connected to {label}, but live stream startup timed out.") from exc
            except Exception as exc:
                await self._device_manager.disconnect()
                self._set_disconnected_state(
                    connection_text="Disconnected",
                    live_status_text="Disconnected",
                    discovery_status_text=f"Connection failed for {label}.",
                    diagnostics_text=f"Connection failed for {label}: {exc}",
                )
                raise RuntimeError(f"Connection failed for {label}: {exc}") from exc

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
            if self._chart_t0 is not None:
                x_value = max((marker.timestamp_utc - self._chart_t0).total_seconds(), 0.0)
                y_value = self._live_points[-1][1] if self._live_points else 0.0
                self._live_marker_points.append((x_value, y_value))
            self._live = replace(
                self._live,
                marker_points=tuple(self._live_marker_points),
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

    def set_export_status(self, message: str) -> None:
        with self._lock:
            self._session = replace(self._session, export_status_text=message)

    async def shutdown(self) -> None:
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
                    selected_summary_text="Min - | Max - | Avg -",
                    selected_unit_text="",
                    selected_session_notes="",
                    selected_markers=(),
                    chart_points=(),
                    marker_points=(),
                )

    def refresh_workflows(self, limit: int = 10) -> None:
        definitions = self._workflow_catalog.list()
        definition_rows = tuple(_workflow_definition_vm(definition) for definition in definitions)
        active_state = self._workflow_runner.active_state()
        selected_id = self.workflow_view_model().selected_workflow_id
        if active_state is not None:
            selected_id = active_state.definition.workflow_id
        elif selected_id is None and definitions:
            selected_id = definitions[0].workflow_id
        selected_definition = None if selected_id is None else self._workflow_catalog.get(selected_id)
        recent_run_models = self._workflow_runner.list_recent_runs(limit=limit)
        recent_runs = tuple(_workflow_run_vm(run) for run in recent_run_models)
        selected_recent_run = None
        if selected_id is not None:
            selected_recent_run = next((run for run in recent_run_models if run.workflow_id == selected_id), None)

        current_title = "No workflow selected"
        current_description = ""
        progress_text = "0/0 steps"
        current_step_title = "No active step"
        current_instruction = ""
        current_requirement = ""
        active_session_text = "No workflow session"
        latest_capture_text = "No captured step yet"
        run_result_text = ""
        completed_steps: tuple[WorkflowStepViewModel, ...] = ()
        is_running = False

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
            active_session_text = active_state.run.session_id
            latest_capture_text = _latest_capture_text(active_state.completed_steps)
            run_result_text = active_state.run.result.value.replace("_", " ").title()
            completed_steps = tuple(_workflow_step_vm(result, selected_definition) for result in active_state.completed_steps)
            is_running = active_state.run.result == WorkflowRunResult.IN_PROGRESS
        elif selected_definition is not None and selected_recent_run is not None:
            results = self._workflow_runner.results_for_run(selected_recent_run.run_id)
            progress_text = f"{len(results)}/{len(selected_definition.steps)} steps"
            current_step_title = (
                "Workflow complete"
                if selected_recent_run.result == WorkflowRunResult.COMPLETED
                else "No active step"
            )
            current_requirement = ""
            active_session_text = selected_recent_run.session_id
            latest_capture_text = _latest_capture_text(results)
            run_result_text = selected_recent_run.result.value.replace("_", " ").title()
            completed_steps = tuple(_workflow_step_vm(result, selected_definition) for result in results)

        with self._lock:
            self._workflow = WorkflowViewModel(
                status_text=self._workflow_status_message,
                selected_workflow_id=selected_id,
                workflows=definition_rows,
                current_title_text=current_title,
                current_description_text=current_description,
                progress_text=progress_text,
                current_step_title=current_step_title,
                current_instruction_text=current_instruction,
                current_requirement_text=current_requirement,
                active_session_text=active_session_text,
                latest_capture_text=latest_capture_text,
                run_result_text=run_result_text,
                is_running=is_running,
                completed_steps=completed_steps,
                recent_runs=recent_runs,
            )

    def report_error(self, message: str) -> None:
        with self._lock:
            self._home = replace(self._home, message_text=message, connection_text=f"Error: {message}")
            self._discovery = replace(self._discovery, status_text=f"Error: {message}")
            self._session = replace(self._session, export_status_text=message)
            self._live = replace(self._live, status_text="Error")
            self._settings = replace(self._settings, diagnostics_text=message)
            self._workflow = replace(self._workflow, status_text=message)
        self._workflow_status_message = message

    def select_device(self, device_id: str | None) -> None:
        with self._lock:
            self._discovery = replace(self._discovery, selected_device_id=device_id)

    def select_workflow(self, workflow_id: str | None) -> None:
        with self._lock:
            self._workflow = replace(self._workflow, selected_workflow_id=workflow_id)
        if workflow_id is not None:
            definition = self._workflow_catalog.get(workflow_id)
            if definition is not None:
                self._workflow_status_message = f"Ready to start {definition.title}."
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
        self._workflow_owned_session_id = session.session_id if owns_session else None
        self._workflow_status_message = f"Started {definition.title}."
        self.add_marker(f"Started workflow: {definition.title}", label="workflow")
        self.refresh_workflows()
        return state.run.run_id

    def complete_workflow_step(self, note: str | None = None) -> str:
        current = self._workflow_runner.active_state()
        if current is None or current.current_step is None:
            raise RuntimeError("Start a workflow before completing steps.")
        step = current.current_step
        latest = self._device_manager.latest_reading()
        state = self._workflow_runner.complete_current_step(latest_reading=latest, note=note)
        detail = f"{current.definition.title}: {step.title}"
        if step.capture and latest is not None:
            detail = f"{detail} ({latest.display_text})"
        self.add_marker(detail, label="workflow")
        self._workflow_status_message = f"Completed step {step.title}."
        self._finish_workflow_if_complete(state)
        self.refresh_workflows()
        return state.run.run_id

    def skip_workflow_step(self, note: str | None = None) -> str:
        current = self._workflow_runner.active_state()
        if current is None or current.current_step is None:
            raise RuntimeError("Start a workflow before skipping steps.")
        step = current.current_step
        state = self._workflow_runner.skip_current_step(note=note)
        self.add_marker(f"Skipped workflow step: {step.title}", label="workflow")
        self._workflow_status_message = f"Skipped step {step.title}."
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
        self.refresh_workflows()
        return run.run_id

    def select_session(self, session_id: str) -> None:
        session = self._store.sessions.get(session_id)
        if session is None:
            raise RuntimeError(f"Unknown session {session_id!r}.")
        readings = self._store.readings.list_for_session(session_id)
        markers = self._store.markers.list_for_session(session_id)
        contexts = tuple(_session_context_view_models(readings))
        current_session = self.session_view_model()
        selected_context_id = current_session.selected_context_id if current_session.selected_session_id == session_id else None
        if selected_context_id is not None and selected_context_id not in {ctx.context_id for ctx in contexts}:
            selected_context_id = None

        filtered_readings = readings if selected_context_id is None else [
            reading for reading in readings if _reading_context_id(reading) == selected_context_id
        ]
        filtered_markers = markers if selected_context_id is None else _markers_for_context(
            readings,
            markers,
            selected_context_id,
        )
        stats = summarize_readings(filtered_readings)
        points = tuple(_chart_points(filtered_readings))
        marker_points = tuple(_marker_points(filtered_readings, filtered_markers))
        marker_rows = tuple(_marker_vm(marker) for marker in filtered_markers)
        unit_text = next((reading.unit for reading in filtered_readings if reading.unit), "")
        context_label = next((ctx.label for ctx in contexts if ctx.context_id == selected_context_id), "")
        with self._lock:
            self._session = replace(
                self._session,
                selected_session_id=session_id,
                selected_context_id=selected_context_id,
                selected_context_label=context_label,
                active_title_text=session.title or session.session_id,
                reading_count_text=f"{len(filtered_readings)} readings",
                available_contexts=contexts,
                selected_summary_text=_summary_text(stats),
                selected_unit_text=unit_text,
                selected_session_notes=session.notes or "",
                selected_markers=marker_rows,
                chart_points=points,
                marker_points=marker_points,
            )

    def select_session_context(self, context_id: str | None) -> None:
        session_id = self.session_view_model().selected_session_id
        if session_id is None:
            return
        with self._lock:
            self._session = replace(self._session, selected_context_id=context_id)
        self.select_session(session_id)

    def on_reading(self, reading: Reading) -> None:
        value = "--" if reading.value is None else f"{reading.value:.6g}"
        timestamp = reading.timestamp_utc.astimezone(timezone.utc).strftime("%H:%M:%S UTC")
        context_key = _reading_context_key(reading)
        banner_text = ""
        with self._lock:
            if self._live_context_key is not None and context_key != self._live_context_key:
                self._reset_live_chart_state(reading.timestamp_utc)
                banner_text = f"Live chart reset after meter mode changed to {_reading_context_label(reading)}."
            elif self._live_context_key is None:
                self._chart_t0 = reading.timestamp_utc
            self._live_context_key = context_key
            self._live_readings.append(reading)
            if reading.value is not None and self._chart_t0 is not None:
                x_value = max((reading.timestamp_utc - self._chart_t0).total_seconds(), 0.0)
                self._live_points.append((x_value, reading.value))
            live_stats = summarize_readings(self._live_readings[-300:])
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
                chart_notice_text=banner_text or self._live.chart_notice_text,
                is_logging=is_logging,
                last_updated_text=timestamp,
                summary_text=_summary_text(live_stats),
                marker_count_text=f"{self._recorder.marker_count()} markers",
                chart_points=tuple(self._live_points),
                marker_points=tuple(self._live_marker_points),
            )
            self._session = replace(
                self._session,
                reading_count_text=f"{self._recorder.reading_count()} readings",
            )
            if self._workflow.is_running:
                self._workflow = replace(self._workflow, latest_capture_text=f"Latest live reading: {reading.display_text}")

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

    def _set_connecting_state(self, target_label: str) -> None:
        status = f"Connecting to {target_label}..."
        with self._lock:
            self._home = replace(self._home, connection_text=status, message_text="")
            self._live = replace(self._live, connection_text=status, status_text="Connecting")
            self._discovery = replace(self._discovery, status_text=status)
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
            )
            self._live = replace(
                self._live,
                connection_text=f"Connected to {label}",
                status_text="Starting stream...",
                chart_points=(),
                marker_points=(),
                chart_notice_text="",
                summary_text="Min - | Max - | Avg -",
                marker_count_text="0 markers",
            )
            self._discovery = replace(
                self._discovery,
                selected_device_id=device.device_id,
                status_text=f"Connected to {label}. Starting live stream...",
            )
            self._settings = replace(
                self._settings,
                diagnostics_text=f"Connected to {label}. Starting BLE notifications...",
            )

    def _set_disconnected_state(
        self,
        *,
        connection_text: str,
        live_status_text: str,
        discovery_status_text: str,
        diagnostics_text: str,
    ) -> None:
        with self._lock:
            self._current_device = None
            self._reset_live_chart_state()
            self._home = replace(
                self._home,
                connection_text=connection_text,
                active_device_text="No device connected",
            )
            self._live = replace(
                self._live,
                connection_text=connection_text,
                status_text=live_status_text,
                is_logging=False,
                session_title=None,
                chart_points=(),
                marker_points=(),
                chart_notice_text="",
                summary_text="Min - | Max - | Avg -",
                marker_count_text="0 markers",
            )
            self._discovery = replace(self._discovery, status_text=discovery_status_text)
            self._settings = replace(self._settings, diagnostics_text=diagnostics_text)

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
    ) -> None:
        with self._lock:
            self._discovery = replace(
                self._discovery,
                is_scanning=self._discovery.is_scanning if is_scanning is _UNCHANGED else is_scanning,
                is_connecting=self._discovery.is_connecting if is_connecting is _UNCHANGED else is_connecting,
            )

    def _reset_live_chart_state(self, start_at: datetime | None = None) -> None:
        self._chart_t0 = start_at
        self._live_context_key = None
        self._live_points.clear()
        self._live_marker_points.clear()
        self._live_readings = []

    def _finish_workflow_if_complete(self, state: WorkflowRunState) -> None:
        if state.run.result != WorkflowRunResult.COMPLETED:
            return
        self._workflow_status_message = f"Completed {state.definition.title}."
        if self._workflow_owned_session_id == state.run.session_id:
            self.stop_logging()
        self._workflow_owned_session_id = None


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


def _reading_context_key(reading: Reading) -> tuple[str, str, str]:
    return (
        reading.measurement_type.value,
        reading.unit or "",
        reading.mode or "",
    )


def _reading_context_id(reading: Reading) -> str:
    return "\x1f".join(_reading_context_key(reading))


def _reading_context_label(reading: Reading) -> str:
    parts = [reading.measurement_type.value.replace("_", " ").title()]
    if reading.unit:
        parts.append(reading.unit)
    if reading.mode:
        parts.append(reading.mode.upper())
    return " / ".join(parts)


def _session_context_view_models(readings: list[Reading]) -> list[SessionContextViewModel]:
    grouped: dict[str, tuple[str, int]] = {}
    ordered_ids: list[str] = []
    for reading in readings:
        context_id = _reading_context_id(reading)
        if context_id not in grouped:
            ordered_ids.append(context_id)
            grouped[context_id] = (_reading_context_label(reading), 0)
        label, count = grouped[context_id]
        grouped[context_id] = (label, count + 1)
    return [
        SessionContextViewModel(
            context_id=context_id,
            label=grouped[context_id][0],
            display_text=f"{grouped[context_id][0]} ({grouped[context_id][1]} readings)",
        )
        for context_id in ordered_ids
    ]


def _markers_for_context(readings: list[Reading], markers: list[SessionMarker], context_id: str) -> list[SessionMarker]:
    if not readings or not markers:
        return []
    selected: list[SessionMarker] = []
    reading_index = 0
    current_context_id = _reading_context_id(readings[reading_index])
    for marker in markers:
        while reading_index + 1 < len(readings) and readings[reading_index + 1].timestamp_utc <= marker.timestamp_utc:
            reading_index += 1
            current_context_id = _reading_context_id(readings[reading_index])
        if current_context_id == context_id:
            selected.append(marker)
    return selected


def _chart_points(readings: list[Reading]) -> list[tuple[float, float]]:
    numeric = [reading for reading in readings if reading.value is not None]
    if not numeric:
        return []
    start = numeric[0].timestamp_utc
    return [
        (max((reading.timestamp_utc - start).total_seconds(), 0.0), float(reading.value))
        for reading in numeric
        if reading.value is not None
    ]


def _marker_points(readings: list[Reading], markers: list[SessionMarker]) -> list[tuple[float, float]]:
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
        marker_values.append((max((marker.timestamp_utc - start).total_seconds(), 0.0), current_value))
    return marker_values


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


def _workflow_requirement_text(step: WorkflowStep) -> str:
    if not step.capture:
        return "Manual checklist step"
    fragments = ["Capture the current live reading"]
    if step.expected_measurement_type is not None:
        fragments.append(f"type {step.expected_measurement_type.value}")
    if step.expected_unit:
        fragments.append(f"unit {step.expected_unit}")
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
