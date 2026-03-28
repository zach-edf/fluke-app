from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_core.models.session import Session


def export_devices_json(devices: Iterable[DeviceInfo], path: str | Path) -> Path:
    return _write_json(path, [device.__dict__ if hasattr(device, "__dict__") else _device_dict(device) for device in devices])


def export_sessions_json(sessions: Iterable[Session], path: str | Path) -> Path:
    return _write_json(path, [session.__dict__ if hasattr(session, "__dict__") else _session_dict(session) for session in sessions])


def export_readings_json(readings: Iterable[Reading], path: str | Path) -> Path:
    return _write_json(path, [reading.as_dict() for reading in readings])


def _write_json(path: str | Path, payload: object) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    return path


def _device_dict(device: DeviceInfo) -> dict[str, object]:
    return {
        "device_id": device.device_id,
        "ble_address": device.ble_address,
        "model_name": device.model_name,
        "profile_id": device.profile_id,
        "nickname": device.nickname,
        "firmware_version": device.firmware_version,
        "serial_number": device.serial_number,
        "support_level": device.support_level,
        "capabilities": list(device.capabilities),
        "rssi": device.rssi,
        "metadata": dict(device.metadata),
    }


def _session_dict(session: Session) -> dict[str, object]:
    return {
        "session_id": session.session_id,
        "device_id": session.device_id,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "title": session.title,
        "notes": session.notes,
        "tags": list(session.tags),
        "app_version": session.app_version,
        "profile_id": session.profile_id,
    }
