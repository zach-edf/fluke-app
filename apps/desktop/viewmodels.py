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
class LiveReadingViewModel:
    main_value: str = "--"
    unit_text: str = ""
    measurement_label: str = "Idle"
    status_text: str = "Disconnected"
    connection_text: str = "Not connected"
    is_logging: bool = False
    session_title: str | None = None
    last_updated_text: str = "-"
    summary_text: str = "Min - | Max - | Avg -"
    marker_count_text: str = "0 markers"
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
    recent_devices: tuple[RecentDeviceViewModel, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveryViewModel:
    status_text: str = "Idle"
    devices: tuple[ScannedDeviceViewModel, ...] = ()
    selected_device_id: str | None = None


@dataclass(frozen=True, slots=True)
class SessionViewModel:
    active_session_id: str | None = None
    selected_session_id: str | None = None
    active_title_text: str = "No active session"
    reading_count_text: str = "0 readings"
    export_status_text: str = ""
    database_path_text: str = ""
    recent_sessions: tuple[SessionSummaryViewModel, ...] = ()
    selected_summary_text: str = "Min - | Max - | Avg -"
    selected_unit_text: str = ""
    selected_session_notes: str = ""
    selected_markers: tuple[SessionMarkerViewModel, ...] = ()
    chart_points: tuple[tuple[float, float], ...] = ()
    marker_points: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class SettingsViewModel:
    database_path_text: str = ""
    export_directory_text: str = ""
    diagnostics_text: str = ""
