from __future__ import annotations

from dataclasses import replace
from typing import Any

from apps.desktop.viewmodels import HomeViewModel, LiveReadingViewModel
from fluke_core.models.reading import Reading


class AppPresenter:
    def __init__(self) -> None:
        self._home = HomeViewModel()
        self._live = LiveReadingViewModel()
        self._reading_handlers: list[Any] = []
        self._logging = False
        self._session_title: str | None = None

    def home_view_model(self) -> HomeViewModel:
        return self._home

    def live_view_model(self) -> LiveReadingViewModel:
        return self._live

    def connect_requested(self, device_label: str) -> None:
        self._home.connection_text = f"Selected {device_label}"
        self._live.connection_text = f"Selected {device_label}"

    def set_connection_status(self, status: str) -> None:
        self._home.connection_text = status
        self._live.connection_text = status

    def set_session_title(self, title: str | None) -> None:
        self._session_title = title
        self._live.session_title = title
        self._home.active_session_text = title or "No active session"

    def set_logging(self, active: bool) -> None:
        self._logging = active
        self._live.is_logging = active

    def on_reading(self, reading: Reading) -> None:
        value = "--" if reading.value is None else f"{reading.value:.6g}"
        self._live = replace(
            self._live,
            main_value=value,
            unit_text=reading.unit,
            measurement_label=reading.measurement_type.value.replace("_", " ").title(),
            status_text=reading.status.value.replace("_", " ").title(),
            session_title=self._session_title,
            is_logging=self._logging,
        )

