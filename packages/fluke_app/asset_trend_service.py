"""Aggregate per-session summary statistics for an asset into trend series.

This reuses the measurement-grouping and unit-normalization concepts from the
export service's replay groups so that a piece of equipment measured across many
sessions produces a clean, chartable time series per measurement type.

Mixed-unit sessions are handled by grouping readings by measurement type plus a
compatible unit family (the export service's ``context_id``), converting every
sample to a common base unit, then choosing a single display unit for the whole
asset-level series so the trend is directly comparable session over session.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median

from fluke_app.export_service import (
    _UNIT_SCALES,
    _base_unit_value,
    _choose_display_unit,
    _context_descriptor,
)
from fluke_app.ports import ReadingRepository, SessionRepository
from fluke_core.models.reading import Reading
from fluke_core.services.statistics import summarize_readings

# Contexts with only a handful of unknown/transitional samples add noise to a
# trend; skip them the same way the export replay groups do.
_UNKNOWN_TREND_THRESHOLD = 5


class AssetRepositoryPort:  # pragma: no cover - documentation only
    def get(self, asset_id: str):
        ...


@dataclass(frozen=True, slots=True)
class TrendPoint:
    """One session's summary for a single measurement context."""

    session_id: str
    session_title: str | None
    started_at: datetime
    reading_count: int
    numeric_count: int
    min_value: float | None
    max_value: float | None
    avg_value: float | None
    median_value: float | None

    def stat(self, name: str) -> float | None:
        return {
            "min": self.min_value,
            "max": self.max_value,
            "avg": self.avg_value,
            "median": self.median_value,
        }.get(name)


@dataclass(frozen=True, slots=True)
class TrendSeries:
    """A time series of per-session summaries for one measurement context."""

    context_id: str
    label: str
    unit: str
    points: tuple[TrendPoint, ...]


@dataclass(frozen=True, slots=True)
class AssetTrend:
    asset_id: str
    session_count: int
    series: tuple[TrendSeries, ...]

    def series_for(self, measurement_type: str) -> TrendSeries | None:
        key = measurement_type.strip().lower()
        for series in self.series:
            if series.context_id.lower() == key or series.label.lower() == key:
                return series
        return None


class AssetTrendService:
    def __init__(
        self,
        session_repo: SessionRepository,
        reading_repo: ReadingRepository,
    ) -> None:
        self._session_repo = session_repo
        self._reading_repo = reading_repo

    def build_trend(
        self,
        asset_id: str,
        *,
        measurement_type: str | None = None,
    ) -> AssetTrend:
        sessions = self._session_repo.list_for_asset(asset_id)
        # Deterministic chronological order for the x-axis.
        sessions = sorted(sessions, key=lambda s: s.started_at)

        # Pass 1: group each session's readings by measurement context and
        # accumulate base-unit values so we can pick one display unit per series.
        labels: dict[str, str] = {}
        normalization_keys: dict[str, str | None] = {}
        raw_units: dict[str, str] = {}
        base_values_by_context: dict[str, list[float]] = {}
        per_session: list[tuple[object, dict[str, list[Reading]]]] = []

        for session in sessions:
            readings = self._reading_repo.list_for_session(session.session_id)
            grouped: dict[str, list[Reading]] = {}
            for reading in readings:
                if reading.value is None:
                    continue
                context_id, label, norm_key, is_unknown = _context_descriptor(reading)
                if is_unknown:
                    continue
                grouped.setdefault(context_id, []).append(reading)
                labels.setdefault(context_id, label)
                normalization_keys.setdefault(context_id, norm_key)
                if norm_key is None and reading.unit:
                    raw_units.setdefault(context_id, reading.unit)
                base = _base_unit_value(reading, norm_key) if norm_key else reading.value
                if base is not None:
                    base_values_by_context.setdefault(context_id, []).append(base)
            per_session.append((session, grouped))

        # Drop tiny unknown-ish contexts that never accumulated enough samples.
        for context_id in list(base_values_by_context):
            if len(base_values_by_context[context_id]) < 1:
                del base_values_by_context[context_id]

        # Pass 2: choose a display unit per context, then convert each session's
        # stats into that unit.
        series_list: list[TrendSeries] = []
        for context_id, base_values in base_values_by_context.items():
            norm_key = normalization_keys.get(context_id)
            if norm_key is not None:
                display_unit = _choose_display_unit(norm_key, list(base_values))
                display_factor = dict(_UNIT_SCALES[norm_key])[display_unit]
            else:
                display_unit = raw_units.get(context_id, "")
                display_factor = 1.0

            points: list[TrendPoint] = []
            for session, grouped in per_session:
                group = grouped.get(context_id)
                if not group:
                    continue
                display_readings = _to_display_readings(group, norm_key, display_factor)
                stats = summarize_readings(display_readings)
                values = [r.value for r in display_readings if r.value is not None]
                med = median(values) if values else None
                points.append(
                    TrendPoint(
                        session_id=session.session_id,
                        session_title=session.title,
                        started_at=session.started_at,
                        reading_count=stats.reading_count,
                        numeric_count=stats.numeric_count,
                        min_value=stats.min_value,
                        max_value=stats.max_value,
                        avg_value=stats.avg_value,
                        median_value=med,
                    )
                )
            if not points:
                continue
            series_list.append(
                TrendSeries(
                    context_id=context_id,
                    label=labels.get(context_id, context_id),
                    unit=display_unit,
                    points=tuple(points),
                )
            )

        # Stable ordering: most-measured contexts first, then label.
        series_list.sort(key=lambda s: (-sum(p.numeric_count for p in s.points), s.label))

        if measurement_type is not None:
            key = measurement_type.strip().lower()
            series_list = [
                s for s in series_list if s.context_id.lower() == key or s.label.lower() == key
            ]

        return AssetTrend(
            asset_id=asset_id,
            session_count=len(sessions),
            series=tuple(series_list),
        )


ASSET_TREND_CSV_HEADERS = (
    "asset_id",
    "measurement",
    "label",
    "unit",
    "session_id",
    "session_title",
    "started_at",
    "reading_count",
    "numeric_count",
    "min",
    "max",
    "avg",
    "median",
)


def export_asset_trend_csv(trend: AssetTrend, path: str | Path) -> str:
    """Write one row per session per measurement group with summary stats."""
    export_path = Path(path)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    with export_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(ASSET_TREND_CSV_HEADERS)
        for series in trend.series:
            for point in series.points:
                writer.writerow(
                    [
                        trend.asset_id,
                        series.context_id,
                        series.label,
                        series.unit,
                        point.session_id,
                        point.session_title or "",
                        point.started_at.isoformat(),
                        point.reading_count,
                        point.numeric_count,
                        _fmt(point.min_value),
                        _fmt(point.max_value),
                        _fmt(point.avg_value),
                        _fmt(point.median_value),
                    ]
                )
    return str(export_path)


def _fmt(value: float | None) -> str:
    return "" if value is None else repr(value)


def _to_display_readings(
    readings: list[Reading],
    normalization_key: str | None,
    display_factor: float,
) -> list[Reading]:
    """Return readings whose values are expressed in the chosen display unit."""
    from dataclasses import replace

    converted: list[Reading] = []
    for reading in readings:
        if reading.value is None:
            converted.append(reading)
            continue
        if normalization_key is None:
            converted.append(reading)
            continue
        base = _base_unit_value(reading, normalization_key)
        if base is None:
            converted.append(reading)
            continue
        converted.append(replace(reading, value=base / display_factor))
    return converted
