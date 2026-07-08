from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Session:
    session_id: str
    device_id: str
    started_at: datetime
    ended_at: datetime | None = None
    title: str | None = None
    notes: str | None = None
    tags: list[str] = field(default_factory=list)
    app_version: str | None = None
    profile_id: str | None = None
    asset_id: str | None = None
