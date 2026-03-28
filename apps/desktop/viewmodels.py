from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LiveReadingViewModel:
    main_value: str = "--"
    unit_text: str = ""
    measurement_label: str = "Idle"
    status_text: str = "Disconnected"
    connection_text: str = "Not connected"
    is_logging: bool = False
    session_title: str | None = None


@dataclass(slots=True)
class HomeViewModel:
    title: str = "Fluke Community Desktop"
    subtitle: str = "Connect, view, and log readings from supported meters."
    connection_text: str = "Disconnected"
    active_session_text: str = "No active session"

