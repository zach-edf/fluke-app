from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Free-text asset_type is intentional, but these categories are suggested to
# keep naming consistent across a fleet of tracked equipment.
SUGGESTED_ASSET_TYPES: tuple[str, ...] = (
    "motor",
    "panel",
    "HVAC unit",
    "battery",
    "charger",
    "transformer",
    "generator",
    "pump",
    "other",
)


@dataclass(slots=True)
class Asset:
    """A piece of equipment that sessions can be attached to for trending."""

    asset_id: str
    name: str
    asset_type: str = ""
    location: str = ""
    notes: str = ""
    created_at: datetime | None = None
