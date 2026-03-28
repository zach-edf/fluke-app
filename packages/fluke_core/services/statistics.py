from __future__ import annotations

from fluke_core.models.reading import Reading
from fluke_core.models.session_stats import SessionStatistics


def summarize_readings(readings: list[Reading]) -> SessionStatistics:
    if not readings:
        return SessionStatistics()

    numeric_values = [reading.value for reading in readings if reading.value is not None]
    min_value = min(numeric_values) if numeric_values else None
    max_value = max(numeric_values) if numeric_values else None
    avg_value = (sum(numeric_values) / len(numeric_values)) if numeric_values else None
    duration_s = 0.0
    if len(readings) >= 2:
        duration_s = max((readings[-1].timestamp_utc - readings[0].timestamp_utc).total_seconds(), 0.0)

    return SessionStatistics(
        reading_count=len(readings),
        numeric_count=len(numeric_values),
        min_value=min_value,
        max_value=max_value,
        avg_value=avg_value,
        duration_s=duration_s,
    )
