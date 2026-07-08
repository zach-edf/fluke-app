from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from fluke_core.models.reading import Reading

# Default number of seconds without a fresh reading before the live view
# considers the data stale. Kept small because field users expect the big
# number on their phone to visibly "freeze" quickly when the meter mode
# changes or the BLE link hiccups.
DEFAULT_STALE_AFTER_S = 3.0

# How many recent points to retain for the rolling live chart. This is a
# display buffer only; nothing here is persisted.
DEFAULT_HISTORY_POINTS = 240


@dataclass(slots=True)
class LiveState:
    """In-memory snapshot of the live reading stream for the web view.

    This is intentionally decoupled from :class:`DeviceManager`. The CLI wires
    device-manager callbacks into :meth:`on_reading` and
    :meth:`set_connection_status`, but tests can drive the same methods
    directly without any BLE machinery.
    """

    stale_after_s: float = DEFAULT_STALE_AFTER_S
    history_points: int = DEFAULT_HISTORY_POINTS

    _latest: Reading | None = field(default=None, init=False)
    _connection_status: str = field(default="connecting", init=False)
    _connection_detail: str = field(default="", init=False)
    _sample_count: int = field(default=0, init=False)
    _numeric_count: int = field(default=0, init=False)
    _min_value: float | None = field(default=None, init=False)
    _max_value: float | None = field(default=None, init=False)
    _sum_value: float = field(default=0.0, init=False)
    _started_monotonic: float = field(default_factory=time.monotonic, init=False)
    _last_reading_monotonic: float | None = field(default=None, init=False)
    _history: deque[tuple[float, float]] = field(default_factory=deque, init=False)

    def __post_init__(self) -> None:
        self._history = deque(maxlen=max(2, int(self.history_points)))

    # -- ingestion ---------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        now = time.monotonic()
        self._latest = reading
        self._sample_count += 1
        self._last_reading_monotonic = now
        # Any reading means the underlying stream is alive again.
        if self._connection_status != "connected":
            self._connection_status = "connected"
            self._connection_detail = ""
        if reading.value is not None:
            value = float(reading.value)
            self._numeric_count += 1
            self._sum_value += value
            self._min_value = value if self._min_value is None else min(self._min_value, value)
            self._max_value = value if self._max_value is None else max(self._max_value, value)
            self._history.append((now - self._started_monotonic, value))

    def set_connection_status(self, status: str, detail: str = "") -> None:
        self._connection_status = status
        self._connection_detail = detail

    def reset_statistics(self) -> None:
        self._sample_count = 0
        self._numeric_count = 0
        self._min_value = None
        self._max_value = None
        self._sum_value = 0.0
        self._started_monotonic = time.monotonic()
        self._last_reading_monotonic = None
        self._history.clear()

    # -- derived views -----------------------------------------------------

    @property
    def latest(self) -> Reading | None:
        return self._latest

    def average(self) -> float | None:
        if self._numeric_count == 0:
            return None
        return self._sum_value / self._numeric_count

    def seconds_since_reading(self) -> float | None:
        if self._last_reading_monotonic is None:
            return None
        return max(0.0, time.monotonic() - self._last_reading_monotonic)

    def is_stale(self) -> bool:
        gap = self.seconds_since_reading()
        if gap is None:
            return True
        return gap > self.stale_after_s

    def uptime_s(self) -> float:
        return max(0.0, time.monotonic() - self._started_monotonic)

    def history(self) -> list[list[float]]:
        return [[round(t, 3), v] for t, v in self._history]

    # -- serialization -----------------------------------------------------

    def snapshot(self, *, include_history: bool = True) -> dict[str, Any]:
        reading = self._latest
        reading_dict = reading.as_dict() if reading is not None else None
        payload: dict[str, Any] = {
            "connection_status": self._connection_status,
            "connection_detail": self._connection_detail,
            "stale": self.is_stale(),
            "stale_after_s": self.stale_after_s,
            "seconds_since_reading": self.seconds_since_reading(),
            "sample_count": self._sample_count,
            "numeric_count": self._numeric_count,
            "min_value": self._min_value,
            "max_value": self._max_value,
            "avg_value": self.average(),
            "uptime_s": round(self.uptime_s(), 3),
            "reading": reading_dict,
        }
        if include_history:
            payload["history"] = self.history()
        return payload

    def latest_payload(self) -> dict[str, Any]:
        reading = self._latest
        return {
            "reading": reading.as_dict() if reading is not None else None,
            "stale": self.is_stale(),
            "seconds_since_reading": self.seconds_since_reading(),
        }
