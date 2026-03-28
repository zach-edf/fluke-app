from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionStatistics:
    reading_count: int = 0
    numeric_count: int = 0
    min_value: float | None = None
    max_value: float | None = None
    avg_value: float | None = None
    duration_s: float = 0.0
