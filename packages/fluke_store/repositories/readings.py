from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.reading import Reading


class ReadingRepository:
    def __init__(self, con: sqlite3.Connection):
        self._con = con

    def append(self, session_id: str, reading: Reading) -> Reading:
        self._con.execute(
            """
            INSERT INTO readings (
                session_id, timestamp_utc, value, unit, measurement_type,
                status, display_text, source_device_id, mode, metadata_json, raw_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                reading.timestamp_utc.isoformat(),
                reading.value,
                reading.unit,
                reading.measurement_type.value,
                reading.status.value,
                reading.display_text,
                reading.source_device_id,
                reading.mode,
                json.dumps(reading.metadata, sort_keys=True),
                reading.raw_payload,
            ),
        )
        self._con.commit()
        return reading

    def list_for_session(self, session_id: str) -> list[Reading]:
        rows = self._con.execute(
            """
            SELECT * FROM readings
            WHERE session_id = ?
            ORDER BY timestamp_utc ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
        return [_reading_from_row(row) for row in rows]


def _reading_from_row(row: sqlite3.Row) -> Reading:
    metadata_raw = row["metadata_json"]
    return Reading(
        timestamp_utc=datetime.fromisoformat(row["timestamp_utc"]),
        value=row["value"],
        unit=row["unit"],
        measurement_type=MeasurementType(row["measurement_type"]),
        status=ReadingStatus(row["status"]),
        display_text=row["display_text"],
        source_device_id=row["source_device_id"],
        mode=row["mode"],
        raw_payload=row["raw_payload"],
        metadata=_metadata_from_json(metadata_raw),
    )


def _metadata_from_json(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
