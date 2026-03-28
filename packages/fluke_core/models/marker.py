from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SessionMarker:
    session_id: str
    timestamp_utc: datetime
    label: str
    note: str = ""
    source: str = "manual"
    marker_id: int | None = None
