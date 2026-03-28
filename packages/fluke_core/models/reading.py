from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fluke_core.enums import MeasurementType, ReadingStatus


@dataclass(frozen=True, slots=True)
class Reading:
    timestamp_utc: datetime
    value: float | None
    unit: str
    measurement_type: MeasurementType
    status: ReadingStatus
    display_text: str
    source_device_id: str
    mode: str = ""
    raw_payload: bytes | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "value": self.value,
            "unit": self.unit,
            "measurement_type": self.measurement_type.value,
            "status": self.status.value,
            "display_text": self.display_text,
            "source_device_id": self.source_device_id,
            "mode": self.mode,
            "metadata": dict(self.metadata),
        }
