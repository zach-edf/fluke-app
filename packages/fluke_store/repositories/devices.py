from __future__ import annotations

from dataclasses import replace
import sqlite3
from datetime import datetime, timezone

from fluke_core.models.device import DeviceInfo


class DeviceRepository:
    def __init__(self, con: sqlite3.Connection):
        self._con = con

    def upsert(self, device: DeviceInfo, last_seen_at: datetime | None = None) -> DeviceInfo:
        last_seen_at = last_seen_at or datetime.now(timezone.utc)
        self._con.execute(
            """
            INSERT INTO devices (
                id, ble_address, model_name, profile_id, nickname,
                firmware_version, serial_number, support_level, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                ble_address=excluded.ble_address,
                model_name=excluded.model_name,
                profile_id=excluded.profile_id,
                nickname=excluded.nickname,
                firmware_version=excluded.firmware_version,
                serial_number=excluded.serial_number,
                support_level=excluded.support_level,
                last_seen_at=excluded.last_seen_at
            """,
            (
                device.device_id,
                device.ble_address,
                device.model_name,
                device.profile_id,
                device.nickname,
                device.firmware_version,
                device.serial_number,
                device.support_level,
                last_seen_at.isoformat(),
            ),
        )
        self._con.commit()
        return replace_device(device, last_seen_at=last_seen_at)

    def get(self, device_id: str) -> DeviceInfo | None:
        row = self._con.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if row is None:
            return None
        return _device_from_row(row)

    def list_recent(self, limit: int = 20) -> list[DeviceInfo]:
        rows = self._con.execute(
            """
            SELECT * FROM devices
            ORDER BY COALESCE(last_seen_at, '') DESC, model_name ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_device_from_row(row) for row in rows]


def _device_from_row(row: sqlite3.Row) -> DeviceInfo:
    return DeviceInfo(
        device_id=row["id"],
        ble_address=row["ble_address"],
        model_name=row["model_name"],
        profile_id=row["profile_id"],
        nickname=row["nickname"],
        firmware_version=row["firmware_version"],
        serial_number=row["serial_number"],
        support_level=row["support_level"],
        metadata={"last_seen_at": row["last_seen_at"]} if row["last_seen_at"] else {},
    )


def replace_device(device: DeviceInfo, *, last_seen_at: datetime | None = None) -> DeviceInfo:
    metadata = dict(device.metadata)
    if last_seen_at is not None:
        metadata["last_seen_at"] = last_seen_at.isoformat()
    return replace(device, metadata=metadata)
