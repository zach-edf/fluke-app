from __future__ import annotations

from contextlib import nullcontext
import sqlite3
from datetime import datetime

from fluke_core.models.marker import SessionMarker


class MarkerRepository:
    def __init__(self, con: sqlite3.Connection, lock=None):
        self._con = con
        self._lock = lock or nullcontext()

    def append(self, session_id: str, marker: SessionMarker) -> SessionMarker:
        with self._lock:
            cursor = self._con.execute(
                """
                INSERT INTO session_markers (session_id, timestamp_utc, label, note, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    marker.timestamp_utc.isoformat(),
                    marker.label,
                    marker.note,
                    marker.source,
                ),
            )
            self._con.commit()
        return SessionMarker(
            session_id=session_id,
            timestamp_utc=marker.timestamp_utc,
            label=marker.label,
            note=marker.note,
            source=marker.source,
            marker_id=cursor.lastrowid,
        )

    def list_for_session(self, session_id: str) -> list[SessionMarker]:
        with self._lock:
            rows = self._con.execute(
                """
                SELECT * FROM session_markers
                WHERE session_id = ?
                ORDER BY timestamp_utc ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        return [_marker_from_row(row) for row in rows]


def _marker_from_row(row: sqlite3.Row) -> SessionMarker:
    return SessionMarker(
        session_id=row["session_id"],
        timestamp_utc=datetime.fromisoformat(row["timestamp_utc"]),
        label=row["label"],
        note=row["note"],
        source=row["source"],
        marker_id=row["id"],
    )
