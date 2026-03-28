from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_core.models.session import Session


@dataclass(slots=True)
class MemorySessionCapture:
    device: DeviceInfo
    title: str | None = None
    notes: str | None = None
    tags: list[str] = field(default_factory=list)
    app_version: str | None = None
    profile_id: str | None = None
    session_id: str = field(init=False)
    started_at: datetime = field(init=False)
    ended_at: datetime | None = field(default=None, init=False)
    readings: list[Reading] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.started_at = datetime.now(timezone.utc)
        self.session_id = _build_session_id(self.device.device_id, self.title)

    @property
    def session(self) -> Session:
        return Session(
            session_id=self.session_id,
            device_id=self.device.device_id,
            started_at=self.started_at,
            ended_at=self.ended_at,
            title=self.title,
            notes=self.notes,
            tags=list(self.tags),
            app_version=self.app_version,
            profile_id=self.profile_id or self.device.profile_id,
        )

    def record(self, reading: Reading) -> None:
        self.readings.append(reading)

    def stop(self) -> Session:
        self.ended_at = datetime.now(timezone.utc)
        return self.session

    def to_csv_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "session_id": self.session_id,
                "timestamp_utc": reading.timestamp_utc.isoformat(),
                "value": "" if reading.value is None else reading.value,
                "unit": reading.unit,
                "measurement_type": reading.measurement_type.value,
                "status": reading.status.value,
                "display_text": reading.display_text,
                "source_device_id": reading.source_device_id,
                "mode": reading.mode,
                "raw_payload": reading.raw_payload.hex() if reading.raw_payload is not None else "",
                "metadata_json": json.dumps(reading.metadata, sort_keys=True),
            }
            for reading in self.readings
        ]

    def export_csv(self, path: Path) -> Path:
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
                    "raw_payload",
                    "metadata_json",
                ],
            )
            writer.writeheader()
            writer.writerows(self.to_csv_rows())
        return path

    def export_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "session": {
                "session_id": self.session_id,
                "device_id": self.device.device_id,
                "started_at": self.started_at.isoformat(),
                "ended_at": self.ended_at.isoformat() if self.ended_at else None,
                "title": self.title,
                "notes": self.notes,
                "tags": list(self.tags),
                "app_version": self.app_version,
                "profile_id": self.profile_id or self.device.profile_id,
            },
            "device": {
                "device_id": self.device.device_id,
                "ble_address": self.device.ble_address,
                "model_name": self.device.model_name,
                "profile_id": self.device.profile_id,
                "nickname": self.device.nickname,
                "support_level": self.device.support_level,
            },
            "readings": [
                {
                    "timestamp_utc": reading.timestamp_utc.isoformat(),
                    "value": reading.value,
                    "unit": reading.unit,
                    "measurement_type": reading.measurement_type.value,
                    "status": reading.status.value,
                    "display_text": reading.display_text,
                    "source_device_id": reading.source_device_id,
                    "mode": reading.mode,
                    "metadata": dict(reading.metadata),
                }
                for reading in self.readings
            ],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path


def _build_session_id(device_id: str, title: str | None) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = (title or "session").replace(" ", "_")
    device_slug = device_id.replace(" ", "_")
    return f"{ts}-{device_slug}-{slug}"
