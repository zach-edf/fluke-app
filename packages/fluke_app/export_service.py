from __future__ import annotations

import csv
import json
from pathlib import Path

from fluke_app.ports import MarkerRepository, ReadingExporter, ReadingRepository, SessionRepository
from fluke_core.models.marker import SessionMarker
from fluke_core.models.reading import Reading
from fluke_core.models.session import Session
from fluke_core.services.statistics import summarize_readings


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
                    "value",
                    "unit",
                    "measurement_type",
                    "status",
                    "display_text",
                    "source_device_id",
                    "mode",
                    "raw_payload_hex",
                ],
            )
            writer.writeheader()
            for reading in readings:
                writer.writerow(
                    {
                        "session_id": session.session_id,
                        "timestamp_utc": reading.timestamp_utc.isoformat(),
                        "value": "" if reading.value is None else repr(reading.value),
                        "unit": reading.unit,
                        "measurement_type": reading.measurement_type.value,
                        "status": reading.status.value,
                        "display_text": reading.display_text,
                        "source_device_id": reading.source_device_id or session.device_id,
                        "mode": reading.mode,
                        "raw_payload_hex": "" if reading.raw_payload is None else reading.raw_payload.hex(),
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
                "nickname": device.nickname,
                "firmware_version": device.firmware_version,
                "serial_number": device.serial_number,
                "support_level": device.support_level,
                "rssi": device.rssi,
                "metadata": dict(device.metadata),
            },
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
