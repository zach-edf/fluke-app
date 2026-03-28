from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_core.models.session import Session


def export_devices_csv(devices: Iterable[DeviceInfo], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "device_id",
                "ble_address",
                "model_name",
                "profile_id",
                "nickname",
                "firmware_version",
                "serial_number",
                "support_level",
                "rssi",
                "metadata_json",
            ],
        )
        writer.writeheader()
        for device in devices:
            writer.writerow(_device_row(device))
    return path


def export_sessions_csv(sessions: Iterable[Session], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "session_id",
                "device_id",
                "started_at",
                "ended_at",
                "title",
                "notes",
                "tags_json",
                "app_version",
                "profile_id",
            ],
        )
        writer.writeheader()
        for session in sessions:
            writer.writerow(_session_row(session))
    return path


def export_readings_csv(readings: Iterable[Reading], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
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
            writer.writerow(_reading_row(reading))
    return path


def _device_row(device: DeviceInfo) -> dict[str, str]:
    return {
        "device_id": device.device_id,
        "ble_address": device.ble_address,
        "model_name": device.model_name,
        "profile_id": device.profile_id,
        "nickname": device.nickname or "",
        "firmware_version": device.firmware_version or "",
        "serial_number": device.serial_number or "",
        "support_level": device.support_level,
        "rssi": "" if device.rssi is None else str(device.rssi),
        "metadata_json": _json(device.metadata),
    }


def _session_row(session: Session) -> dict[str, str]:
    return {
        "session_id": session.session_id,
        "device_id": session.device_id,
        "started_at": session.started_at.isoformat(),
        "ended_at": "" if session.ended_at is None else session.ended_at.isoformat(),
        "title": session.title or "",
        "notes": session.notes or "",
        "tags_json": _json(session.tags),
        "app_version": session.app_version or "",
        "profile_id": session.profile_id or "",
    }


def _reading_row(reading: Reading) -> dict[str, str]:
    return {
        "timestamp_utc": reading.timestamp_utc.isoformat(),
        "value": "" if reading.value is None else repr(reading.value),
        "unit": reading.unit,
        "measurement_type": reading.measurement_type.value,
        "status": reading.status.value,
        "display_text": reading.display_text,
        "source_device_id": reading.source_device_id,
        "mode": reading.mode,
        "raw_payload_hex": "" if reading.raw_payload is None else reading.raw_payload.hex(),
    }


def _json(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=True)
