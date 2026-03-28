from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DeviceInfo:
    device_id: str
    ble_address: str
    model_name: str
    profile_id: str
    nickname: str | None = None
    firmware_version: str | None = None
    serial_number: str | None = None
    support_level: str = "unknown"
    capabilities: list[str] = field(default_factory=list)
    rssi: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
