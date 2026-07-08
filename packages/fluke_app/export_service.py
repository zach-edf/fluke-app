from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import median

from fluke_app.ports import MarkerRepository, ReadingExporter, ReadingRepository, SessionRepository
from fluke_core.models.marker import SessionMarker
from fluke_core.models.reading import Reading
from fluke_core.models.session import Session
from fluke_core.services.statistics import summarize_readings

_UNKNOWN_REPLAY_THRESHOLD = 5
_GAP_THRESHOLD_S = 5.0
_UNIT_SCALES: dict[str, tuple[tuple[str, float], ...]] = {
    "voltage": (("uV", 1e-6), ("mV", 1e-3), ("V", 1.0), ("kV", 1e3)),
    "current": (("uA", 1e-6), ("mA", 1e-3), ("A", 1.0)),
    "resistance": (("ohm", 1.0), ("kOhm", 1e3), ("MOhm", 1e6)),
    "capacitance": (("pF", 1e-12), ("nF", 1e-9), ("uF", 1e-6), ("mF", 1e-3), ("F", 1.0)),
    "frequency": (("Hz", 1.0), ("kHz", 1e3), ("MHz", 1e6)),
}


class ExportService:
    def __init__(
        self,
        session_repo: SessionRepository,
        reading_repo: ReadingRepository,
        marker_repo: MarkerRepository | None,
        csv_exporter: ReadingExporter,
        json_exporter: ReadingExporter,
    ) -> None:
        self._session_repo = session_repo
        self._reading_repo = reading_repo
        self._marker_repo = marker_repo
        self._csv_exporter = csv_exporter
        self._json_exporter = json_exporter

    def export_csv(self, session_id: str, path: str | Path) -> str:
        session, readings = self._load(session_id)
        return str(self._csv_exporter.export(session, readings, Path(path)))

    def export_json(self, session_id: str, path: str | Path) -> str:
        session, readings = self._load(session_id)
        if isinstance(self._json_exporter, SessionJsonExporter):
            self._json_exporter.set_markers(self._load_markers(session_id))
        return str(self._json_exporter.export(session, readings, Path(path)))

    def export_analysis_csv(self, session_id: str, path: str | Path) -> str:
        _session, readings = self._load(session_id)
        export_path = Path(path)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        groups = _build_replay_groups(readings)
        headers = ["timestamp_utc"] + [
            _analysis_column_name(group["context_id"], group["display_unit"])
            for group in groups
        ]
        rows_by_key: dict[tuple[str, str], dict[str, str | float | None]] = {}
        for group in groups:
            column = _analysis_column_name(group["context_id"], group["display_unit"])
            for reading in group["readings"]:
                sample_group_id = str(reading.metadata.get("sample_group_id") or "")
                row = rows_by_key.setdefault(
                    (reading.timestamp_utc.isoformat(), sample_group_id),
                    {
                        "timestamp_utc": reading.timestamp_utc.isoformat(),
                        **{header: None for header in headers[1:]},
                    },
                )
                row[column] = reading.value
        rows = list(rows_by_key.values())
        rows.sort(
            key=lambda row: (
                str(row["timestamp_utc"]),
                headers.index(
                    next(
                        (key for key in headers[1:] if row[key] is not None),
                        headers[1] if len(headers) > 1 else "timestamp_utc",
                    )
                ),
            )
        )
        with export_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return str(export_path)

    def export_segment_summary_json(self, session_id: str, path: str | Path) -> str:
        session, readings = self._load(session_id)
        markers = self._load_markers(session_id)
        export_path = Path(path)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        segments = _derive_segments(readings)
        payload = {
            "session": {
                "session_id": session.session_id,
                "device_id": session.device_id,
                "started_at": session.started_at.isoformat(),
                "ended_at": None if session.ended_at is None else session.ended_at.isoformat(),
                "title": session.title,
                "notes": session.notes,
                "tags": list(session.tags),
                "app_version": session.app_version,
                "profile_id": session.profile_id,
            },
            "segment_count": len(segments),
            "segments": [_segment_payload(segment, markers) for segment in segments],
            "markers": [
                {
                    "marker_id": marker.marker_id,
                    "timestamp_utc": marker.timestamp_utc.isoformat(),
                    "label": marker.label,
                    "note": marker.note,
                    "source": marker.source,
                }
                for marker in markers
            ],
        }
        export_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return str(export_path)

    def export_asset_trend_csv(self, asset_id: str, path: str | Path) -> str:
        # Imported lazily to avoid a circular import (asset_trend_service imports
        # the grouping/normalization helpers from this module).
        from fluke_app.asset_trend_service import (
            AssetTrendService,
            export_asset_trend_csv,
        )

        service = AssetTrendService(self._session_repo, self._reading_repo)
        trend = service.build_trend(asset_id)
        return export_asset_trend_csv(trend, path)

    def _load(self, session_id: str) -> tuple[object, list[object]]:
        session = self._session_repo.get(session_id)
        if session is None:
            raise RuntimeError(f"Unknown session {session_id!r}.")
        readings = self._reading_repo.list_for_session(session_id)
        return session, readings

    def _load_markers(self, session_id: str) -> list[SessionMarker]:
        if self._marker_repo is None:
            return []
        return self._marker_repo.list_for_session(session_id)


class SessionCsvExporter:
    def export(self, session: Session, readings: list[Reading], path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "session_id",
                    "timestamp_utc",
                    "sample_group_id",
                    "channel_role",
                    "family_id",
                    "variant_id",
                    "value",
                    "unit",
                    "measurement_type",
                    "status",
                    "display_text",
                    "source_device_id",
                    "mode",
                    "raw_payload_hex",
                    "metadata_json",
                ],
            )
            writer.writeheader()
            for reading in readings:
                writer.writerow(
                    {
                        "session_id": session.session_id,
                        "timestamp_utc": reading.timestamp_utc.isoformat(),
                        "sample_group_id": str(reading.metadata.get("sample_group_id") or ""),
                        "channel_role": str(reading.metadata.get("channel_role") or "primary"),
                        "family_id": str(reading.metadata.get("family_id") or ""),
                        "variant_id": str(reading.metadata.get("variant_id") or ""),
                        "value": "" if reading.value is None else repr(reading.value),
                        "unit": reading.unit,
                        "measurement_type": reading.measurement_type.value,
                        "status": reading.status.value,
                        "display_text": reading.display_text,
                        "source_device_id": reading.source_device_id or session.device_id,
                        "mode": reading.mode,
                        "raw_payload_hex": "" if reading.raw_payload is None else reading.raw_payload.hex(),
                        "metadata_json": json.dumps(reading.metadata, sort_keys=True),
                    }
                )
        return path


class SessionJsonExporter:
    def __init__(self, device_repo: object | None = None) -> None:
        self._device_repo = device_repo
        self._markers: list[SessionMarker] = []

    def set_markers(self, markers: list[SessionMarker]) -> None:
        self._markers = list(markers)

    def export(self, session: Session, readings: list[Reading], path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        device = None
        if self._device_repo is not None:
            device = self._device_repo.get(session.device_id)
        stats = summarize_readings(readings)

        payload = {
            "session": {
                "session_id": session.session_id,
                "device_id": session.device_id,
                "started_at": session.started_at.isoformat(),
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "title": session.title,
                "notes": session.notes,
                "tags": list(session.tags),
                "app_version": session.app_version,
                "profile_id": session.profile_id,
            },
            "statistics": {
                "reading_count": stats.reading_count,
                "numeric_count": stats.numeric_count,
                "min_value": stats.min_value,
                "max_value": stats.max_value,
                "avg_value": stats.avg_value,
                "duration_s": stats.duration_s,
            },
            "device": None
            if device is None
            else {
                "device_id": device.device_id,
                "ble_address": device.ble_address,
                "model_name": device.model_name,
                "profile_id": device.profile_id,
                "family_id": getattr(device, "family_id", ""),
                "variant_id": getattr(device, "variant_id", ""),
                "nickname": device.nickname,
                "firmware_version": device.firmware_version,
                "serial_number": device.serial_number,
                "support_level": device.support_level,
                "rssi": device.rssi,
                "metadata": dict(device.metadata),
            },
            "available_channels": sorted(
                {
                    str(reading.metadata.get("channel_role") or "primary")
                    for reading in readings
                    if str(reading.metadata.get("channel_role") or "primary") in {"primary", "secondary"}
                }
            ),
            "readings": [
                {
                    "timestamp_utc": reading.timestamp_utc.isoformat(),
                    "value": reading.value,
                    "unit": reading.unit,
                    "measurement_type": reading.measurement_type.value,
                    "status": reading.status.value,
                    "display_text": reading.display_text,
                    "source_device_id": reading.source_device_id or session.device_id,
                    "mode": reading.mode,
                    "raw_payload_hex": None if reading.raw_payload is None else reading.raw_payload.hex(),
                    "metadata": dict(reading.metadata),
                }
                for reading in readings
            ],
            "markers": [
                {
                    "marker_id": marker.marker_id,
                    "timestamp_utc": marker.timestamp_utc.isoformat(),
                    "label": marker.label,
                    "note": marker.note,
                    "source": marker.source,
                }
                for marker in self._markers
            ],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return path


def _analysis_column_name(context_id: str, display_unit: str) -> str:
    base = context_id.replace(":", "_")
    suffix = str(display_unit or "value").strip().lower().replace("+", "plus").replace("%", "pct")
    suffix = "".join(ch if ch.isalnum() else "_" for ch in suffix).strip("_")
    return f"{base}_{suffix}" if suffix else base


def _build_replay_groups(readings: list[Reading]) -> list[dict[str, object]]:
    grouped: dict[str, list[Reading]] = {}
    labels: dict[str, str] = {}
    normalization_keys: dict[str, str | None] = {}
    for reading in readings:
        context_id, label, normalization_key, is_unknown = _context_descriptor(reading)
        current = grouped.setdefault(context_id, [])
        current.append(reading)
        labels[context_id] = label
        normalization_keys[context_id] = normalization_key
        if is_unknown:
            labels.setdefault(context_id, "Unknown / Transitional")

    has_known_groups = any(context_id != "unknown" for context_id in grouped)
    groups: list[dict[str, object]] = []
    for context_id, raw_group in grouped.items():
        numeric_count = sum(1 for reading in raw_group if reading.value is not None)
        if numeric_count == 0:
            continue
        if context_id == "unknown" and has_known_groups and len(raw_group) <= _UNKNOWN_REPLAY_THRESHOLD:
            continue
        normalization_key = normalization_keys[context_id]
        normalized = _normalize_group(raw_group, normalization_key)
        display_unit = next((reading.unit for reading in normalized if reading.unit), "")
        groups.append(
            {
                "context_id": context_id,
                "label": labels[context_id],
                "readings": normalized,
                "display_unit": display_unit,
            }
        )
    groups.sort(key=lambda item: (-len(item["readings"]), str(item["label"])))
    return groups


def _derive_segments(readings: list[Reading]) -> list[dict[str, object]]:
    segments: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for reading in readings:
        context_id, label, normalization_key, _ = _context_descriptor(reading)
        if reading.value is None:
            continue
        if current is None:
            current = {
                "context_id": context_id,
                "label": label,
                "normalization_key": normalization_key,
                "raw_readings": [reading],
            }
            continue
        previous = current["raw_readings"][-1]
        gap_s = max((reading.timestamp_utc - previous.timestamp_utc).total_seconds(), 0.0)
        if current["context_id"] != context_id or gap_s > _GAP_THRESHOLD_S:
            segments.append(current)
            current = {
                "context_id": context_id,
                "label": label,
                "normalization_key": normalization_key,
                "raw_readings": [reading],
            }
            continue
        current["raw_readings"].append(reading)
    if current is not None:
        segments.append(current)

    finalized: list[dict[str, object]] = []
    for index, segment in enumerate(segments, start=1):
        raw_readings = list(segment["raw_readings"])
        normalized = _normalize_group(raw_readings, segment["normalization_key"])
        display_unit = next((reading.unit for reading in normalized if reading.unit), "")
        finalized.append(
            {
                "segment_id": f"segment_{index}",
                "segment_index": index,
                "context_id": segment["context_id"],
                "label": segment["label"],
                "measurement_type": normalized[0].measurement_type.value if normalized else "unknown",
                "unit": display_unit,
                "mode": normalized[0].mode if normalized else "",
                "readings": normalized,
                "start_utc": normalized[0].timestamp_utc if normalized else None,
                "end_utc": normalized[-1].timestamp_utc if normalized else None,
            }
        )
    return finalized


def _segment_payload(segment: dict[str, object], markers: list[SessionMarker]) -> dict[str, object]:
    readings = list(segment["readings"])
    stats = summarize_readings(readings)
    start_utc = segment["start_utc"]
    end_utc = segment["end_utc"]
    segment_markers = [
        {
            "marker_id": marker.marker_id,
            "timestamp_utc": marker.timestamp_utc.isoformat(),
            "label": marker.label,
            "note": marker.note,
            "source": marker.source,
        }
        for marker in markers
        if start_utc is not None and end_utc is not None and start_utc <= marker.timestamp_utc <= end_utc
    ]
    return {
        "segment_id": segment["segment_id"],
        "segment_index": segment["segment_index"],
        "context_id": segment["context_id"],
        "label": segment["label"],
        "measurement_type": segment["measurement_type"],
        "unit": segment["unit"],
        "mode": segment["mode"],
        "start_utc": None if start_utc is None else start_utc.isoformat(),
        "end_utc": None if end_utc is None else end_utc.isoformat(),
        "sample_count": len(readings),
        "statistics": {
            "reading_count": stats.reading_count,
            "numeric_count": stats.numeric_count,
            "min_value": stats.min_value,
            "max_value": stats.max_value,
            "avg_value": stats.avg_value,
            "duration_s": stats.duration_s,
        },
        "markers": segment_markers,
    }


def _context_descriptor(reading: Reading) -> tuple[str, str, str | None, bool]:
    measurement_type = reading.measurement_type
    unit_family = str(reading.metadata.get("unit_family") or "").strip().lower()
    channel_role = str(reading.metadata.get("channel_role") or "primary").strip().lower()
    multi_channel = any(f"mode_attr_{index}" in reading.metadata for index in range(1, 6))

    if measurement_type.value == "voltage_ac":
        return _channel_aware_context("voltage_ac", "Voltage AC", "voltage", channel_role, multi_channel)
    if measurement_type.value == "voltage_dc":
        return _channel_aware_context("voltage_dc", "Voltage DC", "voltage", channel_role, multi_channel)
    if measurement_type.value == "current_ac":
        return _channel_aware_context("current_ac", "Current AC", "current", channel_role, multi_channel)
    if measurement_type.value == "current_dc":
        return _channel_aware_context("current_dc", "Current DC", "current", channel_role, multi_channel)
    if measurement_type.value == "current_ac_dc":
        return _channel_aware_context("current_acdc", "Current AC+DC", "current", channel_role, multi_channel)
    if measurement_type.value == "current_inrush":
        return _channel_aware_context("current_inrush", "Current Inrush", "current", channel_role, multi_channel)
    if measurement_type.value == "resistance":
        return _channel_aware_context("resistance", "Resistance", "resistance", channel_role, multi_channel)
    if measurement_type.value == "capacitance":
        return _channel_aware_context("capacitance", "Capacitance", "capacitance", channel_role, multi_channel)
    if measurement_type.value == "frequency":
        return _channel_aware_context("frequency", "Frequency", "frequency", channel_role, multi_channel)
    if measurement_type.value == "duty_cycle":
        return _channel_aware_context("duty_cycle", "Duty Cycle", None, channel_role, multi_channel)
    if measurement_type.value == "temperature":
        context_id = f"temperature:{reading.unit or 'unknown'}"
        return _channel_aware_context(context_id, f"Temperature {reading.unit}".strip(), None, channel_role, multi_channel)
    if measurement_type.value == "continuity":
        return _channel_aware_context("continuity", "Continuity", None, channel_role, multi_channel)

    if unit_family == "voltage":
        if reading.mode == "ac":
            return _channel_aware_context("voltage_ac", "Voltage AC", "voltage", channel_role, multi_channel)
        if reading.mode == "dc" or reading.unit == "mV":
            return _channel_aware_context("voltage_dc", "Voltage DC", "voltage", channel_role, multi_channel)
        return _channel_aware_context("voltage", "Voltage", "voltage", channel_role, multi_channel)
    if unit_family == "current":
        if reading.mode == "ac":
            return _channel_aware_context("current_ac", "Current AC", "current", channel_role, multi_channel)
        if reading.mode == "dc":
            return _channel_aware_context("current_dc", "Current DC", "current", channel_role, multi_channel)
        if reading.mode == "acdc":
            return _channel_aware_context("current_acdc", "Current AC+DC", "current", channel_role, multi_channel)
        return _channel_aware_context("current", "Current", "current", channel_role, multi_channel)
    if unit_family == "resistance":
        return _channel_aware_context("resistance", "Resistance", "resistance", channel_role, multi_channel)
    if unit_family == "capacitance":
        return _channel_aware_context("capacitance", "Capacitance", "capacitance", channel_role, multi_channel)
    if unit_family == "frequency":
        return _channel_aware_context("frequency", "Frequency", "frequency", channel_role, multi_channel)
    if unit_family == "duty_cycle":
        return _channel_aware_context("duty_cycle", "Duty Cycle", None, channel_role, multi_channel)
    if unit_family == "temperature":
        context_id = f"temperature:{reading.unit or 'unknown'}"
        return _channel_aware_context(context_id, f"Temperature {reading.unit}".strip(), None, channel_role, multi_channel)

    return _channel_aware_context("unknown", "Unknown / Transitional", None, channel_role, multi_channel, is_unknown=True)


def _channel_aware_context(
    context_id: str,
    label: str,
    normalization_key: str | None,
    channel_role: str,
    multi_channel: bool,
    *,
    is_unknown: bool = False,
) -> tuple[str, str, str | None, bool]:
    if not multi_channel:
        return context_id, label, normalization_key, is_unknown
    prefix = "secondary" if channel_role == "secondary" else "primary"
    return f"{prefix}_{context_id}", f"{prefix.title()} {label}", normalization_key, is_unknown


def _normalize_group(readings: list[Reading], normalization_key: str | None) -> list[Reading]:
    if normalization_key is None:
        return list(readings)
    unit_scale = dict(_UNIT_SCALES[normalization_key])
    base_values = [_base_unit_value(reading, normalization_key) for reading in readings if reading.value is not None]
    display_unit = _choose_display_unit(normalization_key, base_values)
    display_factor = unit_scale[display_unit]
    normalized: list[Reading] = []
    for reading in readings:
        if reading.value is None:
            normalized.append(reading)
            continue
        base_value = _base_unit_value(reading, normalization_key)
        if base_value is None:
            normalized.append(reading)
            continue
        normalized.append(Reading(
            timestamp_utc=reading.timestamp_utc,
            value=base_value / display_factor,
            unit=display_unit,
            measurement_type=reading.measurement_type,
            status=reading.status,
            display_text=reading.display_text,
            source_device_id=reading.source_device_id,
            mode=reading.mode,
            raw_payload=reading.raw_payload,
            metadata=dict(reading.metadata),
        ))
    return normalized


def _base_unit_value(reading: Reading, normalization_key: str) -> float | None:
    if reading.value is None:
        return None
    unit_scale = dict(_UNIT_SCALES.get(normalization_key, ()))
    factor = unit_scale.get(reading.unit)
    if factor is None:
        return float(reading.value)
    return float(reading.value) * factor


def _choose_display_unit(normalization_key: str, base_values: list[float | None]) -> str:
    units = _UNIT_SCALES[normalization_key]
    numeric_values = [abs(value) for value in base_values if value is not None]
    if not numeric_values:
        return units[-1][0]
    typical = median(numeric_values)
    if typical == 0:
        return units[-1][0]
    for unit, factor in reversed(units):
        if typical / factor >= 1:
            return unit
    return units[0][0]
