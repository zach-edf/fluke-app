from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScannedDeviceViewModel:
    device_id: str
    label: str
    model_name: str
    rssi_text: str
    support_text: str


@dataclass(frozen=True, slots=True)
class SessionSummaryViewModel:
    session_id: str
    title: str
    started_at_text: str
    ended_at_text: str


@dataclass(frozen=True, slots=True)
class RecentDeviceViewModel:
    device_id: str
    label: str
    support_text: str
    last_seen_text: str


@dataclass(frozen=True, slots=True)
class SessionMarkerViewModel:
    marker_id: int | None
    timestamp_text: str
    label: str
    note: str


@dataclass(frozen=True, slots=True)
class SessionContextViewModel:
    context_id: str
    label: str
    display_text: str


@dataclass(frozen=True, slots=True)
class SessionSegmentViewModel:
    segment_id: str
    label: str
    display_text: str


@dataclass(frozen=True, slots=True)
class SessionCompareViewModel:
    session_id: str
    label: str
    display_text: str


@dataclass(frozen=True, slots=True)
class DeviceMemorySessionViewModel:
    preview_id: str
    title: str
    started_at_text: str
    ended_at_text: str
    measurement_text: str
    interval_text: str
    detail_count_text: str
    import_status_text: str


@dataclass(frozen=True, slots=True)
class WorkflowDefinitionViewModel:
    workflow_id: str
    title: str
    category: str
    description: str
    step_count_text: str


@dataclass(frozen=True, slots=True)
class WorkflowStepViewModel:
    step_id: str
    title: str
    instruction: str
    status_text: str
    detail_text: str


@dataclass(frozen=True, slots=True)
class WorkflowRunSummaryViewModel:
    run_id: str
    workflow_id: str
    title: str
    session_id: str
    started_at_text: str
    result_text: str


@dataclass(frozen=True, slots=True)
class LiveReadingViewModel:
    main_value: str = "--"
    unit_text: str = ""
    measurement_label: str = "Idle"
    available_capabilities: tuple[str, ...] = ()
    live_primary_reading: str = "--"
    live_primary_unit_text: str = ""
    live_primary_label: str = "Primary"
    live_secondary_reading: str = "--"
    live_secondary_unit_text: str = ""
    live_secondary_label: str = "Secondary"
    family_mode_badges: tuple[str, ...] = ()
    capability_summary_text: str = ""
    selected_live_channel: str = "primary"
    status_text: str = "Disconnected"
    connection_text: str = "Not connected"
    is_connected: bool = False
    connection_health: str = "idle"
    chart_notice_text: str = ""
    is_logging: bool = False
    session_title: str | None = None
    last_updated_text: str = "-"
    summary_text: str = "Min - | Max - | Avg -"
    marker_count_text: str = "0 markers"
    alert_status_text: str = "Alerts disabled."
    alert_active: bool = False
    alert_message: str = ""
    alert_event_id: int = 0
    selected_chart_mode: str = "rolling_30s"
    chart_x_mode: str = "elapsed"
    chart_x_title: str = "Seconds"
    logging_interval_seconds_text: str = ""
    logging_duration_seconds_text: str = ""
    logging_manual_stop: bool = False
    logging_status_text: str = "Logging settings unavailable."
    chart_points: tuple[tuple[float, float], ...] = ()
    marker_points: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class HomeViewModel:
    title: str = "Fluke Community Desktop"
    subtitle: str = "Connect, view, and log readings from supported meters."
    connection_text: str = "Disconnected"
    active_session_text: str = "No active session"
    active_device_text: str = "No device connected"
    message_text: str = ""
    is_busy: bool = False
    is_connected: bool = False
    connection_health: str = "idle"
    recent_devices: tuple[RecentDeviceViewModel, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveryViewModel:
    status_text: str = "Idle"
    devices: tuple[ScannedDeviceViewModel, ...] = ()
    selected_device_id: str | None = None
    is_scanning: bool = False
    is_connecting: bool = False
    is_reconnecting: bool = False


@dataclass(frozen=True, slots=True)
class SessionViewModel:
    active_session_id: str | None = None
    selected_session_id: str | None = None
    selected_context_id: str | None = None
    selected_context_label: str = ""
    selected_replay_channel: str = "primary"
    available_replay_channels: tuple[str, ...] = ()
    device_memory_status_text: str = "Device memory unavailable."
    device_memory_capacity_text: str = ""
    device_memory_summary_text: str = ""
    device_memory_value_source: str = "average"
    device_memory_sessions: tuple[DeviceMemorySessionViewModel, ...] = ()
    selected_axis_mode: str = "elapsed"
    selected_segment_id: str | None = None
    compare_session_id: str | None = None
    compare_session_label: str = ""
    active_title_text: str = "No active session"
    reading_count_text: str = "0 readings"
    export_status_text: str = ""
    database_path_text: str = ""
    recent_sessions: tuple[SessionSummaryViewModel, ...] = ()
    available_contexts: tuple[SessionContextViewModel, ...] = ()
    available_segments: tuple[SessionSegmentViewModel, ...] = ()
    available_compare_sessions: tuple[SessionCompareViewModel, ...] = ()
    selected_summary_text: str = "Min - | Max - | Avg -"
    compare_summary_text: str = ""
    selected_unit_text: str = ""
    selected_session_notes: str = ""
    chart_x_mode: str = "elapsed"
    chart_x_title: str = "Seconds"
    selected_markers: tuple[SessionMarkerViewModel, ...] = ()
    chart_points: tuple[tuple[float, float], ...] = ()
    compare_chart_points: tuple[tuple[float, float], ...] = ()
    marker_points: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class SettingsViewModel:
    database_path_text: str = ""
    export_directory_text: str = ""
    diagnostics_text: str = ""
    active_device_text: str = "No device connected"
    active_family_text: str = ""
    active_profile_text: str = ""
    active_services_text: str = ""
    active_capabilities_text: str = ""
    live_buffer_text: str = ""
    fixture_status_text: str = ""
    theme: str = "light"
    auto_reconnect_enabled: bool = True


@dataclass(frozen=True, slots=True)
class WorkflowViewModel:
    status_text: str = "Select a workflow to review the steps."
    selected_workflow_id: str | None = None
    selected_run_id: str | None = None
    workflows: tuple[WorkflowDefinitionViewModel, ...] = ()
    current_title_text: str = "No workflow selected"
    current_description_text: str = ""
    progress_text: str = "0/0 steps"
    current_step_title: str = "No active step"
    current_instruction_text: str = ""
    current_requirement_text: str = ""
    current_interaction_mode_text: str = ""
    capture_state_text: str = ""
    capture_hint_text: str = ""
    active_session_text: str = "No workflow session"
    latest_capture_text: str = "No captured step yet"
    run_result_text: str = ""
    selected_run_summary_text: str = "No workflow run selected"
    report_text: str = ""
    is_running: bool = False
    primary_action_text: str = "Complete Step"
    can_continue_capture: bool = False
    can_retake_capture: bool = False
    completed_steps: tuple[WorkflowStepViewModel, ...] = ()
    recent_runs: tuple[WorkflowRunSummaryViewModel, ...] = ()
