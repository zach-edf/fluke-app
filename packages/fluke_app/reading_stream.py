from __future__ import annotations

from fluke_app.bus import EventBus
from fluke_core.models.reading import Reading


class ReadingStreamService:
    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._bus = event_bus
        self._latest: Reading | None = None

    def on_readings(self, readings: list[Reading]) -> None:
        for reading in readings:
            self._latest = reading
            if self._bus is not None:
                self._bus.publish(reading)

    def latest(self) -> Reading | None:
        return self._latest
